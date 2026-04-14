"""AI Agent 엔진 — 규칙 기반 긴급 대응 + LLM Tool Calling 미세 조정."""

import json
import logging
from collections import deque
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import httpx

from app.config import settings
from app.sensor_filter import filter_sensors
from app.weather_client import get_weather
from app.ai_agent_prompts import SYSTEM_PROMPT, build_trigger_prompt
from app.tools.definitions import get_active_tools
from app.tools.executor import execute_tool, set_sensor_snapshot

logger = logging.getLogger("ai_agent")

KST = timezone(timedelta(hours=9))

# ─── 설정 ───

ENABLED_PHASES: int = 5  # 전체 활성 (환기+관수+조명+차광/보온)
MAX_TOOL_TURNS: int = 6  # LLM tool-calling 최대 턴 수

# ─── 상태 저장소 (인메모리) ───

agent_enabled: bool = False
_last_daily_reset: str = ""

crop_profile: dict = {
    "name": "토마토",
    "growth_stage": "개화기",
    "optimal_temp": [20, 28],
    "optimal_humidity": [60, 80],
    "optimal_light_hours": 14,
    "nutrient_ratio": {"N": 1.0, "P": 1.2, "K": 1.5},
}

control_state: dict = {
    "ventilation": {"window_open_pct": 0, "fan_speed": 0},
    "irrigation": {
        "valve_open": False,
        "daily_total_L": 0.0,
        "last_watered": None,
        "nutrient": {"N": 1.0, "P": 1.0, "K": 1.0},
    },
    "lighting": {"on": False, "brightness_pct": 0},
    "shading": {"shade_pct": 0, "insulation_pct": 0},
}

decision_history: deque[dict] = deque(maxlen=500)
_last_llm_call: datetime | None = None
_last_sensor_data: dict | None = None

CROP_PRESETS: dict[str, dict] = {
    "토마토": {"name": "토마토", "growth_stage": "개화기", "optimal_temp": [20, 28], "optimal_humidity": [60, 80], "optimal_light_hours": 14, "nutrient_ratio": {"N": 1.0, "P": 1.2, "K": 1.5}},
    "딸기": {"name": "딸기", "growth_stage": "착과기", "optimal_temp": [15, 25], "optimal_humidity": [60, 75], "optimal_light_hours": 12, "nutrient_ratio": {"N": 0.8, "P": 1.0, "K": 1.5}},
    "상추": {"name": "상추", "growth_stage": "영양생장기", "optimal_temp": [15, 22], "optimal_humidity": [60, 70], "optimal_light_hours": 12, "nutrient_ratio": {"N": 1.5, "P": 0.8, "K": 1.0}},
    "고추": {"name": "고추", "growth_stage": "개화기", "optimal_temp": [22, 30], "optimal_humidity": [60, 75], "optimal_light_hours": 14, "nutrient_ratio": {"N": 1.2, "P": 1.0, "K": 1.3}},
    "오이": {"name": "오이", "growth_stage": "영양생장기", "optimal_temp": [20, 28], "optimal_humidity": [70, 85], "optimal_light_hours": 13, "nutrient_ratio": {"N": 1.3, "P": 1.0, "K": 1.2}},
}


# ─── 규칙 기반 판단 (긴급 대응 — 30초마다 실행) ───

def _apply_emergency_rules(sensor_data: dict, weather: dict) -> list[dict]:
    """긴급/이상 상황 규칙. 고온·고습·강수·토양수분·동해 방지."""
    decisions: list[dict] = []
    temp = sensor_data["temperature"]
    humidity = sensor_data["humidity"]
    soil = sensor_data.get("soil_moisture") or 50
    now = datetime.now(KST)
    is_night = now.hour >= 20 or now.hour < 6
    ext_temp = weather.get("current", {}).get("temperature")

    precip = weather.get("current", {}).get("precipitation", 0)
    precip_type = weather.get("current", {}).get("precipitation_type", "없음")

    # ── 긴급: 고온 ──
    if temp > 35:
        control_state["ventilation"] = {"window_open_pct": 100, "fan_speed": 3000}
        decisions.append(_record_decision("ventilation", control_state["ventilation"], f"내부 온도 {temp}C — 긴급 냉각. 창문 100%, 팬 최대.", "emergency", "rule"))
    elif temp > 30 and ext_temp is not None and ext_temp < temp:
        pct = min(100, int((temp - 28) * 20))
        control_state["ventilation"] = {"window_open_pct": pct, "fan_speed": 1500}
        decisions.append(_record_decision("ventilation", control_state["ventilation"], f"내부 {temp}C > 외부 {ext_temp}C. 자연환기 {pct}%.", "high", "rule"))

    # ── 긴급: 고습도 ──
    if humidity > 90 and control_state["ventilation"]["fan_speed"] < 1500:
        control_state["ventilation"]["fan_speed"] = 1500
        if not (is_night and ext_temp is not None and ext_temp < 5):
            control_state["ventilation"]["window_open_pct"] = max(
                control_state["ventilation"]["window_open_pct"], 50
            )
        decisions.append(_record_decision("ventilation", control_state["ventilation"], f"습도 {humidity}% — 결로/병해 방지 환기.", "high", "rule"))

    # ── 긴급: 강수 시 창문 닫기 ──
    if (precip > 0 or precip_type != "없음") and control_state["ventilation"]["window_open_pct"] > 0:
        control_state["ventilation"]["window_open_pct"] = 0
        decisions.append(_record_decision("ventilation", control_state["ventilation"], f"강수 감지({precip_type} {precip}mm) — 창문 닫음.", "high", "rule"))

    # ── 긴급: 토양수분 극저 ──
    if soil < 30:
        water = 3.0
        control_state["irrigation"]["valve_open"] = True
        control_state["irrigation"]["daily_total_L"] += water
        control_state["irrigation"]["last_watered"] = now.isoformat()
        decisions.append(_record_decision("irrigation", {"water_amount_L": water}, f"토양수분 {soil}% — 긴급 관수 {water}L.", "emergency", "rule"))

    # ── 긴급: 야간 동해 방지 ──
    if is_night and ext_temp is not None and ext_temp < 5:
        control_state["shading"]["insulation_pct"] = 100
        control_state["ventilation"]["window_open_pct"] = 0
        decisions.append(_record_decision("shading", control_state["shading"], f"야간 외부 {ext_temp}C — 동해 방지 보온커튼 100%.", "emergency", "rule"))
    elif is_night and ext_temp is not None and ext_temp < 10:
        ins = max(control_state["shading"]["insulation_pct"], 70)
        control_state["shading"]["insulation_pct"] = ins
        decisions.append(_record_decision("shading", control_state["shading"], f"야간 외부 {ext_temp}C — 보온커튼 {ins}%.", "medium", "rule"))

    return decisions


def _apply_general_rules(sensor_data: dict, weather: dict) -> list[dict]:
    """회복/정상화 및 조명/차광 규칙."""
    decisions: list[dict] = []
    temp = sensor_data["temperature"]
    humidity = sensor_data["humidity"]
    soil = sensor_data.get("soil_moisture") or 50
    light = sensor_data.get("light_intensity", 0)
    now = datetime.now(KST)
    is_night = now.hour >= 20 or now.hour < 6

    # ── 일반: 온도/습도 정상 시 환기 해제 ──
    temp_ok = temp <= 30
    humidity_ok = humidity <= 80
    ventilation_active = control_state["ventilation"]["fan_speed"] > 0 or control_state["ventilation"]["window_open_pct"] > 0
    if temp_ok and humidity_ok and ventilation_active:
        control_state["ventilation"] = {"window_open_pct": 0, "fan_speed": 0}
        decisions.append(_record_decision("ventilation", control_state["ventilation"], f"온도 {temp}C, 습도 {humidity}% — 정상 범위. 환기 해제.", "low", "rule"))

    # ── 일반: 토양수분 정상 시 관수 밸브 닫기 ──
    if soil >= 50 and control_state["irrigation"]["valve_open"]:
        control_state["irrigation"]["valve_open"] = False
        decisions.append(_record_decision("irrigation", {"valve_open": False}, f"토양수분 {soil}% — 정상. 관수 밸브 닫힘.", "low", "rule"))

    # ── 일반: 주간 저조도 시 보광등 ON ──
    if not is_night and light < 5000 and not control_state["lighting"]["on"]:
        control_state["lighting"] = {"on": True, "brightness_pct": 60}
        decisions.append(_record_decision("lighting", control_state["lighting"], f"주간 조도 {light} lux — 일조 부족. 보광등 60%.", "medium", "rule"))

    # ── 일반: 주간 조도 충분 시 보광등 OFF ──
    if not is_night and light >= 30000 and control_state["lighting"]["on"]:
        control_state["lighting"] = {"on": False, "brightness_pct": 0}
        decisions.append(_record_decision("lighting", control_state["lighting"], f"주간 조도 {light} lux — 충분. 보광등 OFF.", "low", "rule"))

    # ── 일반: 고조도 시 차광막 ──
    if not is_night and light > 70000 and control_state["shading"]["shade_pct"] < 50:
        control_state["shading"]["shade_pct"] = 50
        decisions.append(_record_decision("shading", control_state["shading"], f"조도 {light} lux — 과도한 일사. 차광막 50%.", "medium", "rule"))

    # ── 일반: 조도 정상 시 차광막 해제 ──
    if light <= 50000 and control_state["shading"]["shade_pct"] > 0:
        control_state["shading"]["shade_pct"] = 0
        decisions.append(_record_decision("shading", control_state["shading"], f"조도 {light} lux — 정상. 차광막 해제.", "low", "rule"))

    # ── 일반: 주간 보온 해제 ──
    if not is_night and control_state["shading"]["insulation_pct"] > 0:
        control_state["shading"]["insulation_pct"] = 0
        decisions.append(_record_decision("shading", control_state["shading"], "주간 — 보온커튼 해제.", "low", "rule"))

    # ── 야간 조명 OFF ──
    if is_night and control_state["lighting"]["on"]:
        control_state["lighting"] = {"on": False, "brightness_pct": 0}
        decisions.append(_record_decision("lighting", control_state["lighting"], "야간 암기 유지 — 조명 OFF.", "low", "rule"))

    return decisions


def _apply_rules(sensor_data: dict, weather: dict) -> list[dict]:
    """규칙 기반 즉시 대응. 긴급/이상 상황에서 LLM 없이 바로 제어."""
    decisions: list[dict] = []
    decisions.extend(_apply_emergency_rules(sensor_data, weather))
    decisions.extend(_apply_general_rules(sensor_data, weather))
    return decisions


# ─── LLM Tool Calling 루프 (5분 간격 미세 조정) ───

async def _run_agent_loop(sensor_data: dict, reliability: dict) -> list[dict]:
    """Multi-turn tool-calling loop. LLM이 센서를 읽고 제어 도구를 호출한다."""
    global _last_llm_call

    if not settings.OPENROUTER_API_KEY:
        logger.debug("OPENROUTER_API_KEY 미설정 — LLM 호출 건너뜀.")
        return []

    now = datetime.now(timezone.utc)
    if _last_llm_call and (now - _last_llm_call).total_seconds() < settings.AI_AGENT_LLM_INTERVAL:
        return []

    tools = get_active_tools(ENABLED_PHASES)

    # 기상/제어/작물 데이터를 트리거 프롬프트에 직접 포함 (read_sensors 의존 제거)
    weather_data = await get_weather(sensor_data)
    trigger_prompt = build_trigger_prompt(
        sensor_data, reliability,
        weather=weather_data,
        control_st=control_state,
        crop_prof=crop_profile,
    )

    # 스냅샷도 설정 (read_sensors 호출 시 사용)
    set_sensor_snapshot({
        "temperature": sensor_data["temperature"],
        "humidity": sensor_data["humidity"],
        "light_intensity": sensor_data["light_intensity"],
        "soil_moisture": sensor_data.get("soil_moisture"),
        "timestamp": datetime.now(KST).isoformat(),
    })

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": trigger_prompt},
    ]

    decisions: list[dict] = []
    tool_call_traces: list[dict] = []

    for turn in range(MAX_TOOL_TURNS):
        try:
            response = await _call_openrouter(messages, tools)
        except Exception as e:
            logger.error("LLM 호출 실패 (turn %d): %s", turn, e)
            break

        message = response["choices"][0]["message"]
        messages.append(message)

        tool_calls = message.get("tool_calls")
        if not tool_calls:
            # LLM이 텍스트 응답 = 판단 완료
            summary = message.get("content", "")
            if summary:
                logger.info("AI Agent 판단 요약: %s", summary[:200])
            break

        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            fn_args = json.loads(tc["function"]["arguments"]) if tc["function"].get("arguments") else {}

            result = await execute_tool(fn_name, fn_args)

            tool_call_traces.append({
                "tool": fn_name,
                "arguments": fn_args,
                "result": result,
            })

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(result, ensure_ascii=False, default=str),
            })

            # 제어 tool 호출이면 decision은 executor에서 이미 기록됨
            if fn_name.startswith("control_") and result.get("success"):
                decisions.append({
                    "tool": fn_name,
                    "args": fn_args,
                    "result": result,
                })

    _last_llm_call = now
    set_sensor_snapshot(None)  # 스냅샷 해제

    # 최신 decision에 tool_call trace 첨부
    if decision_history and tool_call_traces:
        decision_history[0]["tool_calls"] = tool_call_traces

    return decisions


async def _call_openrouter(messages: list[dict], tools: list[dict]) -> dict:
    """OpenRouter API 호출 (OpenAI-compatible function calling)."""
    url = f"{settings.OPENROUTER_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"}
    payload = {
        "model": settings.AI_AGENT_MODEL,
        "messages": messages,
        "tools": tools,
        "temperature": 0.3,
        "max_tokens": 2048,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


# ─── 유틸리티 ───

def _record_decision(
    control_type: str,
    action: dict,
    reason: str,
    priority: str = "medium",
    source: str = "tool",
) -> dict:
    """판단 기록을 생성하고 히스토리에 추가."""
    decision = {
        "id": str(uuid4()),
        "timestamp": datetime.now(KST).isoformat(),
        "control_type": control_type,
        "action": action,
        "reason": reason,
        "priority": priority,
        "source": source,
    }
    decision_history.appendleft(decision)
    return decision


def _has_significant_change(new_data: dict) -> bool:
    """센서값에 유의미한 변화가 있는지 판단."""
    if _last_sensor_data is None:
        return True
    for key in ["temperature", "humidity", "light_intensity"]:
        old = _last_sensor_data.get(key, 0)
        new = new_data.get(key, 0)
        if old == 0:
            if new != 0:
                return True
            continue
        if abs(new - old) / abs(old) > 0.05:
            return True
    old_soil = _last_sensor_data.get("soil_moisture") or 50
    new_soil = new_data.get("soil_moisture") or 50
    if abs(new_soil - old_soil) > 3:
        return True
    return False


# ─── 메인 판단 함수 ───

async def process_sensor_data(raw_sensors: dict) -> list[dict]:
    """센서 데이터 수신 시 호출. 규칙 엔진 + LLM 루프 순차 실행."""
    global _last_sensor_data, _last_daily_reset

    if not agent_enabled:
        return []

    # 일일 관수량 리셋 (자정 기준)
    today = datetime.now(KST).strftime("%Y-%m-%d")
    if _last_daily_reset != today:
        control_state["irrigation"]["daily_total_L"] = 0.0
        _last_daily_reset = today

    # 센서 필터링
    filtered = filter_sensors(raw_sensors)
    sensor_data = {
        "temperature": filtered["temperature"],
        "humidity": filtered["humidity"],
        "light_intensity": filtered["light_intensity"],
        "soil_moisture": filtered.get("soil_moisture"),
    }
    reliability = filtered["reliability"]

    # 기상 데이터 조회
    weather = await get_weather(sensor_data)

    # 1) 규칙 엔진 (긴급 대응, 매 호출)
    rule_decisions = _apply_rules(sensor_data, weather)

    # 2) LLM Tool Calling (유의미 변화 시에만, 간격 제한)
    llm_decisions = []
    if _has_significant_change(sensor_data):
        llm_decisions = await _run_agent_loop(sensor_data, reliability)

    _last_sensor_data = sensor_data.copy()
    return rule_decisions + llm_decisions


# ─── 공개 API 함수 ───

def get_status() -> dict:
    return {
        "enabled": agent_enabled,
        "control_state": control_state,
        "crop_profile": crop_profile,
        "latest_decision": decision_history[0] if decision_history else None,
        "total_decisions": len(decision_history),
    }


def get_decisions(limit: int = 20) -> list[dict]:
    return list(decision_history)[:limit]


def toggle_agent() -> bool:
    global agent_enabled
    agent_enabled = not agent_enabled
    return agent_enabled


def update_crop_profile(data: dict) -> dict:
    global crop_profile
    crop_profile = {
        "name": data["name"],
        "growth_stage": data["growth_stage"],
        "optimal_temp": data["optimal_temp"],
        "optimal_humidity": data["optimal_humidity"],
        "optimal_light_hours": data["optimal_light_hours"],
        "nutrient_ratio": data.get("nutrient_ratio", {"N": 1.0, "P": 1.0, "K": 1.0}),
    }
    return crop_profile


def override_control(control_type: str, values: dict, reason: str) -> dict:
    if control_type in control_state:
        control_state[control_type].update(values)
    return _record_decision(control_type, values, f"수동 오버라이드: {reason}", "high", "manual")


def get_crop_presets() -> dict[str, dict]:
    return CROP_PRESETS
