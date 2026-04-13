"""센서 이상값 필터링 — 조도센서(KY-018) 불안정 대응 포함."""

from collections import deque
from datetime import datetime, timezone

# 센서별 최근 값 버퍼 (이동평균용)
_light_history: deque[float] = deque(maxlen=10)
_temp_history: deque[float] = deque(maxlen=10)
_humidity_history: deque[float] = deque(maxlen=10)

# 조도 0 연속 카운트
_light_zero_streak: int = 0

# 마지막 유효 조도값
_last_valid_light: float = 0.0


def _is_daytime() -> bool:
    """현재 시간이 낮인지 판단 (06:00~20:00 KST)."""
    now = datetime.now(timezone.utc)
    kst_hour = (now.hour + 9) % 24
    return 6 <= kst_hour < 20


def _moving_average(history: deque[float]) -> float:
    """이동평균 계산."""
    if not history:
        return 0.0
    return sum(history) / len(history)


def filter_sensors(sensors: dict) -> dict:
    """센서값을 필터링하고 신뢰도 플래그를 부여한다.

    Returns:
        {
            "temperature": float,
            "humidity": float,
            "light_intensity": float,
            "soil_moisture": float | None,
            "reliability": {
                "temperature": "reliable" | "suspicious" | "unreliable",
                "humidity": "reliable" | "suspicious" | "unreliable",
                "light_intensity": "reliable" | "suspicious" | "unreliable",
            }
        }
    """
    global _light_zero_streak, _last_valid_light

    temp = sensors["temperature"]
    humidity = sensors["humidity"]
    light = sensors["light_intensity"]
    soil = sensors.get("soil_moisture")

    reliability = {
        "temperature": "reliable",
        "humidity": "reliable",
        "light_intensity": "reliable",
    }

    # --- 온도 필터 ---
    if _temp_history:
        avg = _moving_average(_temp_history)
        if avg > 0 and abs(temp - avg) / avg > 0.8:
            reliability["temperature"] = "suspicious"
    _temp_history.append(temp)

    # --- 습도 필터 ---
    if _humidity_history:
        avg = _moving_average(_humidity_history)
        if avg > 0 and abs(humidity - avg) / avg > 0.8:
            reliability["humidity"] = "suspicious"
    _humidity_history.append(humidity)

    # --- 조도 필터 (핵심: 불안정 센서 대응) ---
    raw_light = light  # 히스토리에는 원본 센서값만 기록

    if light == 0:
        _light_zero_streak += 1

        if _light_zero_streak < 3 and _is_daytime():
            # 낮시간에 0이 3회 미만 → 이전 유효값으로 대체
            light = _last_valid_light
            reliability["light_intensity"] = "suspicious"
        elif _is_daytime():
            # 낮시간에 0이 3회 이상 연속 → 센서 장애 판정
            light = _last_valid_light
            reliability["light_intensity"] = "unreliable"
        # 야간 + 0 → 정상 (raw_light=0 그대로 히스토리에 기록)
    else:
        _light_zero_streak = 0

        # 급격한 변화 체크
        if _light_history:
            avg = _moving_average(_light_history)
            if avg > 0 and abs(light - avg) / avg > 0.8:
                reliability["light_intensity"] = "suspicious"

        _last_valid_light = light

    _light_history.append(raw_light)

    return {
        "temperature": temp,
        "humidity": humidity,
        "light_intensity": light,
        "soil_moisture": soil,
        "reliability": reliability,
    }
