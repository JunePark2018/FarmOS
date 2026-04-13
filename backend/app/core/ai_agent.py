"""AI Agent 엔진 — 규칙 기반 + LLM 종합 판단으로 온실 가상 제어."""

import asyncio
import json
import logging
from collections import deque
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import httpx

from app.core.config import settings
from app.core.sensor_filter import filter_sensors
from app.core.weather_client import get_weather
from app.core.ai_agent_prompts import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger("ai_agent")

KST = timezone(timedelta(hours=9))

# ─── 상태 저장소 (인메모리) ───

agent_enabled: bool = False

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

# 마지막 LLM 호출 시각
_last_llm_call: datetime | None = None

# 일일 관수량 리셋 추적
_last_daily_reset: str = ""

# 마지막으로 Agent가 처리한 센서 데이터
_last_sensor_data: dict | None = None

# 백그라운드 루프 태스크
_agent_task: asyncio.Task | None = None


# ─── 작물 프리셋 ───

CROP_PRESETS: dict[str, dict] = {
    "토마토": {
        "name": "토마토", "growth_stage": "개화기",
        "optimal_temp": [20, 28], "optimal_humidity": [60, 80],
        "optimal_light_hours": 14,
        "nutrient_ratio": {"N": 1.0, "P": 1.2, "K": 1.5},
    },
    "딸기": {
        "name": "딸기", "growth_stage": "착과기",
        "optimal_temp": [15, 25], "optimal_humidity": [60, 75],
        "optimal_light_hours": 12,
        "nutrient_ratio": {"N": 0.8, "P": 1.0, "K": 1.5},
    },
    "상추": {
        "name": "상추", "growth_stage": "영양생장기",
        "optimal_temp": [15, 22], "optimal_humidity": [60, 70],
        "optimal_light_hours": 12,
        "nutrient_ratio": {"N": 1.5, "P": 0.8, "K": 1.0},
    },
    "고추": {
        "name": "고추", "growth_stage": "개화기",
        "optimal_temp": [22, 30], "optimal_humidity": [60, 75],
        "optimal_light_hours": 14,
        "nutrient_ratio": {"N": 1.2, "P": 1.0, "K": 1.3},
    },
    "오이": {
        "name": "오이", "growth_stage": "영양생장기",
        "optimal_temp": [20, 28], "optimal_humidity": [70, 85],
        "optimal_light_hours": 13,
        "nutrient_ratio": {"N": 1.3, "P": 1.0, "K": 1.2},
    },
}


# ─── 규칙 기반 판단 ───

def _apply_rules(sensor_data: dict, weather: dict) -> list[dict]:
    """긴급 상황에 대한 규칙 기반 즉시 판단."""
    decisions: list[dict] = []
    temp = sensor_data["temperature"]
    humidity = sensor_data["humidity"]
    soil = sensor_data.get("soil_moisture") or 50
    now = datetime.now(KST)
    is_night = now.hour >= 20 or now.hour < 6

    ext_temp = weather.get("current", {}).get("temperature")

    # --- 정상 복귀 판단 ---
    temp_ok = temp <= 30
    humidity_ok = humidity <= 80
    precip_now = weather.get("current", {}).get("precipitation", 0)
    precip_type_now = weather.get("current", {}).get("precipitation_type", "없음")
    no_precip = precip_now == 0 and precip_type_now == "없음"
    light = sensor_data.get("light_intensity", 0)
    optimal_temp = crop_profile.get("optimal_temp", [20, 28])

    # 온도/습도 모두 정상이면 환기 해제
    ventilation_active = control_state["ventilation"]["fan_speed"] > 0 or control_state["ventilation"]["window_open_pct"] > 0
    if temp_ok and humidity_ok and ventilation_active:
        control_state["ventilation"] = {"window_open_pct": 0, "fan_speed": 0}
        decisions.append(_make_decision("ventilation", control_state["ventilation"], f"온도 {temp}C, 습도 {humidity}% — 정상 범위. 환기 해제.", "low", "rule"))

    # 강수 끝나면 환기 상태를 현재 온도/습도에 맞게 복구
    was_closed_by_rain = any(
        d["reason"].startswith("강수 감지") and d["control_type"] == "ventilation"
        for d in list(decision_history)[:5]
    )
    if no_precip and was_closed_by_rain and control_state["ventilation"]["window_open_pct"] == 0 and (temp > optimal_temp[1] or humidity > 80):
        pct = min(100, int((temp - optimal_temp[0]) * 10))
        control_state["ventilation"]["window_open_pct"] = max(30, pct)
        decisions.append(_make_decision("ventilation", control_state["ventilation"], f"강수 종료. 온도 {temp}C/습도 {humidity}% 감안하여 창문 재개방.", "medium", "rule"))

    # 토양수분 정상이면 관수 밸브 닫기
    if soil >= 50 and control_state["irrigation"]["valve_open"]:
        control_state["irrigation"]["valve_open"] = False
        decisions.append(_make_decision("irrigation", {"valve_open": False}, f"토양수분 {soil}% — 정상. 관수 밸브 닫힘.", "low", "rule"))

    # 낮시간이면 보온 해제
    if not is_night and control_state["shading"]["insulation_pct"] > 0:
        control_state["shading"]["insulation_pct"] = 0
        decisions.append(_make_decision("shading", control_state["shading"], "주간 — 보온커튼 해제.", "low", "rule"))

    # 주간 + 조도 부족 시 보광등 ON
    if not is_night and light < 5000 and not control_state["lighting"]["on"]:
        control_state["lighting"] = {"on": True, "brightness_pct": 60}
        decisions.append(_make_decision("lighting", control_state["lighting"], f"주간 조도 {light} lux — 일조 부족. 보광등 60%.", "medium", "rule"))

    # 주간 + 조도 충분하면 보광등 OFF
    if not is_night and light >= 30000 and control_state["lighting"]["on"]:
        control_state["lighting"] = {"on": False, "brightness_pct": 0}
        decisions.append(_make_decision("lighting", control_state["lighting"], f"주간 조도 {light} lux — 충분. 보광등 OFF.", "low", "rule"))

    # 고조도 시 차광막 가동
    if not is_night and light > 70000 and control_state["shading"]["shade_pct"] < 50:
        control_state["shading"]["shade_pct"] = 50
        decisions.append(_make_decision("shading", control_state["shading"], f"조도 {light} lux — 과도한 일사. 차광막 50%.", "medium", "rule"))

    # 조도 정상이면 차광막 해제
    if light <= 50000 and control_state["shading"]["shade_pct"] > 0:
        control_state["shading"]["shade_pct"] = 0
        decisions.append(_make_decision("shading", control_state["shading"], f"조도 {light} lux — 정상. 차광막 해제.", "low", "rule"))

    # --- 이상 상황 판단 ---
    # 고온 긴급 환기
    if temp > 35:
        control_state["ventilation"] = {"window_open_pct": 100, "fan_speed": 3000}
        decisions.append(_make_decision(
            "ventilation", control_state["ventilation"],
            f"내부 온도 {temp}C — 긴급 냉각. 창문 100%, 팬 최대.",
            "emergency", "rule",
        ))

    # 고온 환기 (30~35C)
    elif temp > 30:
        if ext_temp is not None and ext_temp < temp:
            pct = min(100, int((temp - 28) * 20))
            control_state["ventilation"] = {"window_open_pct": pct, "fan_speed": 1500}
            decisions.append(_make_decision(
                "ventilation", control_state["ventilation"],
                f"내부 {temp}C > 외부 {ext_temp}C. 자연환기 {pct}%.",
                "high", "rule",
            ))

    # 고습도 환기
    if humidity > 90:
        if control_state["ventilation"]["fan_speed"] < 1500:
            control_state["ventilation"]["fan_speed"] = 1500
            if not (is_night and ext_temp is not None and ext_temp < 5):
                control_state["ventilation"]["window_open_pct"] = max(
                    control_state["ventilation"]["window_open_pct"], 50
                )
            decisions.append(_make_decision(
                "ventilation", control_state["ventilation"],
                f"습도 {humidity}% — 결로/병해 방지 환기.",
                "high", "rule",
            ))

    # 강수 시 창문 닫기
    precip = weather.get("current", {}).get("precipitation", 0)
    precip_type = weather.get("current", {}).get("precipitation_type", "없음")
    if precip > 0 or precip_type != "없음":
        if control_state["ventilation"]["window_open_pct"] > 0:
            control_state["ventilation"]["window_open_pct"] = 0
            decisions.append(_make_decision(
                "ventilation", control_state["ventilation"],
                f"강수 감지({precip_type} {precip}mm) — 창문 닫음. 팬으로 내부 순환.",
                "high", "rule",
            ))

    # 토양수분 긴급 관수
    if soil < 30:
        water = 3.0  # 긴급 관수량
        control_state["irrigation"]["valve_open"] = True
        control_state["irrigation"]["daily_total_L"] += water
        control_state["irrigation"]["last_watered"] = now.isoformat()
        decisions.append(_make_decision(
            "irrigation",
            {"water_amount_L": water, "nutrient_ratio": crop_profile["nutrient_ratio"]},
            f"토양수분 {soil}% — 긴급 관수 {water}L.",
            "emergency", "rule",
        ))

    # 야간 보온
    if is_night and ext_temp is not None and ext_temp < 5:
        control_state["shading"]["insulation_pct"] = 100
        control_state["ventilation"]["window_open_pct"] = 0
        decisions.append(_make_decision(
            "shading", control_state["shading"],
            f"야간 외부 {ext_temp}C — 동해 방지 보온커튼 100%.",
            "emergency", "rule",
        ))

    elif is_night and ext_temp is not None and ext_temp < 10:
        ins = max(control_state["shading"]["insulation_pct"], 70)
        control_state["shading"]["insulation_pct"] = ins
        decisions.append(_make_decision(
            "shading", control_state["shading"],
            f"야간 외부 {ext_temp}C — 보온커튼 {ins}%.",
            "medium", "rule",
        ))

    # 야간 조명 OFF
    if is_night and control_state["lighting"]["on"]:
        control_state["lighting"] = {"on": False, "brightness_pct": 0}
        decisions.append(_make_decision(
            "lighting", control_state["lighting"],
            "야간 암기 유지 — 조명 OFF.",
            "low", "rule",
        ))

    return decisions


# ─── LLM 기반 판단 ───

async def _call_llm(sensor_data: dict, weather: dict, reliability: dict) -> list[dict]:
    """OpenRouter GPT-5-nano를 호출하여 종합 판단."""
    global _last_llm_call

    if not settings.OPENROUTER_API_KEY:
        logger.warning("OPENROUTER_API_KEY 미설정 — LLM 판단 건너뜀")
        return []

    # 호출 간격 제한
    now = datetime.now(timezone.utc)
    if _last_llm_call and (now - _last_llm_call).total_seconds() < settings.AI_AGENT_LLM_INTERVAL:
        return []

    user_prompt = build_user_prompt(sensor_data, weather, crop_profile, control_state, reliability)

    url = f"{settings.OPENROUTER_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"}
    payload = {
        "model": settings.AI_AGENT_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 1024,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()

        data = resp.json()
        content = data["choices"][0]["message"]["content"] or ""
        parsed = _extract_json(content)

        if not parsed:
            logger.warning("LLM 응답 JSON 파싱 실패: %s", content[:200])
            return []

        _last_llm_call = now
        return _apply_llm_result(parsed)

    except Exception as e:
        logger.error("LLM 호출 실패: %s", e)
        return []


def _extract_json(text: str) -> dict | None:
    """LLM 응답에서 JSON 추출 (journal_parser.py 패턴 재사용)."""
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                try:
                    return json.loads(part)
                except json.JSONDecodeError:
                    continue
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                return None
    return None


def _apply_llm_result(parsed: dict) -> list[dict]:
    """LLM 판단 결과를 제어 상태에 적용."""
    decisions: list[dict] = []
    reason = parsed.get("reason", "LLM 판단")

    if "ventilation" in parsed:
        v = parsed["ventilation"]
        control_state["ventilation"] = {
            "window_open_pct": max(0, min(100, int(v.get("window_open_pct", 0)))),
            "fan_speed": max(0, min(3000, int(v.get("fan_speed", 0)))),
        }
        decisions.append(_make_decision("ventilation", control_state["ventilation"], reason, "medium", "llm"))

    if "irrigation" in parsed:
        ir = parsed["irrigation"]
        water = float(ir.get("water_amount_L", 0))
        if water > 0:
            control_state["irrigation"]["valve_open"] = True
            control_state["irrigation"]["daily_total_L"] += water
            control_state["irrigation"]["last_watered"] = datetime.now(KST).isoformat()
            nr = ir.get("nutrient_ratio", {})
            control_state["irrigation"]["nutrient"] = {
                "N": float(nr.get("N", 1.0)),
                "P": float(nr.get("P", 1.0)),
                "K": float(nr.get("K", 1.0)),
            }
        else:
            control_state["irrigation"]["valve_open"] = False
        decisions.append(_make_decision("irrigation", ir, reason, "medium", "llm"))

    if "lighting" in parsed:
        lt = parsed["lighting"]
        control_state["lighting"] = {
            "on": bool(lt.get("on", False)),
            "brightness_pct": max(0, min(100, int(lt.get("brightness_pct", 0)))),
        }
        decisions.append(_make_decision("lighting", control_state["lighting"], reason, "low", "llm"))

    if "shading" in parsed:
        sh = parsed["shading"]
        control_state["shading"] = {
            "shade_pct": max(0, min(100, int(sh.get("shade_pct", 0)))),
            "insulation_pct": max(0, min(100, int(sh.get("insulation_pct", 0)))),
        }
        decisions.append(_make_decision("shading", control_state["shading"], reason, "low", "llm"))

    return decisions


# ─── 유틸리티 ───

def _make_decision(
    control_type: str, action: dict, reason: str, priority: str, source: str
) -> dict:
    """판단 이력 레코드 생성."""
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
    """이전 센서 데이터 대비 의미 있는 변화가 있는지 판단."""
    if _last_sensor_data is None:
        return True

    for key in ["temperature", "humidity", "light_intensity"]:
        old = _last_sensor_data.get(key, 0)
        new = new_data.get(key, 0)
        if old == 0:
            if new != 0:
                return True
            continue
        if abs(new - old) / abs(old) > 0.05:  # 5% 이상 변화
            return True

    old_soil = _last_sensor_data.get("soil_moisture") or 50
    new_soil = new_data.get("soil_moisture") or 50
    if abs(new_soil - old_soil) > 3:  # 토양수분 3%p 이상 변화
        return True

    return False


# ─── 메인 판단 함수 ───

async def process_sensor_data(raw_sensors: dict) -> list[dict]:
    """센서 데이터를 받아 필터링 → 규칙 → LLM 판단을 수행한다.

    store.py의 add_reading()에서 호출된다.
    """
    global _last_sensor_data, _last_daily_reset

    if not agent_enabled:
        return []

    # 일일 관수량 리셋 (자정 기준)
    today = datetime.now(KST).strftime("%Y-%m-%d")
    if _last_daily_reset != today:
        control_state["irrigation"]["daily_total_L"] = 0.0
        _last_daily_reset = today

    # 1. 센서 필터링
    filtered = filter_sensors(raw_sensors)
    sensor_data = {
        "temperature": filtered["temperature"],
        "humidity": filtered["humidity"],
        "light_intensity": filtered["light_intensity"],
        "soil_moisture": filtered.get("soil_moisture"),
    }
    reliability = filtered["reliability"]

    # 2. 기상 데이터
    weather = await get_weather(sensor_data)

    # 3. 규칙 기반 판단 (항상 실행)
    rule_decisions = _apply_rules(sensor_data, weather)

    # 4. LLM 판단 (변화 감지 시 + 간격 제한)
    llm_decisions = []
    if _has_significant_change(sensor_data):
        llm_decisions = await _call_llm(sensor_data, weather, reliability)

    _last_sensor_data = sensor_data.copy()

    return rule_decisions + llm_decisions


# ─── 공개 API 함수 ───

def get_status() -> dict:
    """Agent 현재 상태 반환."""
    latest_decision = decision_history[0] if decision_history else None
    return {
        "enabled": agent_enabled,
        "control_state": control_state,
        "crop_profile": crop_profile,
        "latest_decision": latest_decision,
        "total_decisions": len(decision_history),
    }


def get_decisions(limit: int = 20) -> list[dict]:
    """판단 이력 반환."""
    return list(decision_history)[:limit]


def toggle_agent() -> bool:
    """Agent ON/OFF 토글."""
    global agent_enabled
    agent_enabled = not agent_enabled
    logger.info("AI Agent %s", "활성화" if agent_enabled else "비활성화")
    return agent_enabled


def update_crop_profile(data: dict) -> dict:
    """작물 프로필 업데이트."""
    global crop_profile
    crop_profile = {
        "name": data["name"],
        "growth_stage": data["growth_stage"],
        "optimal_temp": data["optimal_temp"],
        "optimal_humidity": data["optimal_humidity"],
        "optimal_light_hours": data["optimal_light_hours"],
        "nutrient_ratio": data.get("nutrient_ratio", {"N": 1.0, "P": 1.0, "K": 1.0}),
    }
    logger.info("작물 프로필 업데이트: %s (%s)", crop_profile["name"], crop_profile["growth_stage"])
    return crop_profile


def override_control(control_type: str, values: dict, reason: str) -> dict:
    """수동 오버라이드."""
    if control_type == "ventilation":
        control_state["ventilation"].update(values)
    elif control_type == "irrigation":
        control_state["irrigation"].update(values)
    elif control_type == "lighting":
        control_state["lighting"].update(values)
    elif control_type == "shading":
        control_state["shading"].update(values)

    decision = _make_decision(control_type, values, f"수동 오버라이드: {reason}", "high", "manual")
    return decision


def get_crop_presets() -> dict[str, dict]:
    """작물 프리셋 목록 반환."""
    return CROP_PRESETS
