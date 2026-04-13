"""센서 이상값 필터링 — 조도센서(KY-018) 불안정 대응 포함."""

from collections import deque
from datetime import datetime, timezone

_light_history: deque[float] = deque(maxlen=10)
_temp_history: deque[float] = deque(maxlen=10)
_humidity_history: deque[float] = deque(maxlen=10)
_light_zero_streak: int = 0
_last_valid_light: float = 0.0


def _is_daytime() -> bool:
    now = datetime.now(timezone.utc)
    kst_hour = (now.hour + 9) % 24
    return 6 <= kst_hour < 20


def _moving_average(history: deque[float]) -> float:
    if not history:
        return 0.0
    return sum(history) / len(history)


def filter_sensors(sensors: dict) -> dict:
    """센서값을 필터링하고 신뢰도 플래그를 부여한다."""
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

    if _temp_history:
        avg = _moving_average(_temp_history)
        if avg > 0 and abs(temp - avg) / avg > 0.8:
            reliability["temperature"] = "suspicious"
    _temp_history.append(temp)

    if _humidity_history:
        avg = _moving_average(_humidity_history)
        if avg > 0 and abs(humidity - avg) / avg > 0.8:
            reliability["humidity"] = "suspicious"
    _humidity_history.append(humidity)

    raw_light = light

    if light == 0:
        _light_zero_streak += 1
        if _light_zero_streak < 3 and _is_daytime():
            light = _last_valid_light
            reliability["light_intensity"] = "suspicious"
        elif _is_daytime():
            light = _last_valid_light
            reliability["light_intensity"] = "unreliable"
    else:
        _light_zero_streak = 0
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
