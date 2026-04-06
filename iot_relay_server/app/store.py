import random
from collections import deque
from datetime import datetime, timezone
from uuid import uuid4

from app.config import settings

MAX_READINGS = 2000

sensor_readings: deque[dict] = deque(maxlen=MAX_READINGS)
irrigation_events: list[dict] = []
sensor_alerts: list[dict] = []


def _random_soil_moisture() -> float:
    return round(random.uniform(20.0, 90.0), 1)


def add_reading(device_id: str, sensors: dict, timestamp: datetime | None = None) -> list[dict]:
    ts = timestamp or datetime.now(timezone.utc)

    soil_moisture = sensors.get("soil_moisture")
    if soil_moisture is None:
        soil_moisture = _random_soil_moisture()

    reading = {
        "device_id": device_id,
        "timestamp": ts.isoformat(),
        "soilMoisture": soil_moisture,
        "temperature": sensors["temperature"],
        "humidity": sensors["humidity"],
        "lightIntensity": sensors["light_intensity"],
    }
    sensor_readings.appendleft(reading)

    new_alerts: list[dict] = []

    if soil_moisture < settings.SOIL_MOISTURE_LOW:
        alert = {
            "id": str(uuid4()),
            "type": "moisture",
            "severity": "경고",
            "message": f"토양 습도가 {soil_moisture}%로 임계값 이하입니다",
            "timestamp": ts.isoformat(),
            "resolved": False,
        }
        sensor_alerts.append(alert)
        new_alerts.append(alert)

        irrigation_events.append({
            "id": str(uuid4()),
            "triggeredAt": ts.isoformat(),
            "reason": f"토양 습도 {soil_moisture}% — 임계값({settings.SOIL_MOISTURE_LOW}%) 이하",
            "valveAction": "열림",
            "duration": 30,
            "autoTriggered": True,
        })

    if sensors["humidity"] > 90:
        alert = {
            "id": str(uuid4()),
            "type": "humidity",
            "severity": "주의",
            "message": f"대기 습도 {sensors['humidity']}%. 병해 발생 위험 증가",
            "timestamp": ts.isoformat(),
            "resolved": False,
        }
        sensor_alerts.append(alert)
        new_alerts.append(alert)

    return new_alerts


def get_latest() -> dict | None:
    return sensor_readings[0] if sensor_readings else None


def get_history(limit: int = 300) -> list[dict]:
    items = list(sensor_readings)[:limit]
    items.reverse()
    return items


def get_alerts(resolved: bool | None = None) -> list[dict]:
    if resolved is None:
        return list(reversed(sensor_alerts))
    return [a for a in reversed(sensor_alerts) if a["resolved"] == resolved]


def resolve_alert(alert_id: str) -> bool:
    for a in sensor_alerts:
        if a["id"] == alert_id:
            a["resolved"] = True
            return True
    return False


def get_irrigation_events() -> list[dict]:
    return list(reversed(irrigation_events))


def add_irrigation_event(valve_action: str, reason: str) -> dict:
    event = {
        "id": str(uuid4()),
        "triggeredAt": datetime.now(timezone.utc).isoformat(),
        "reason": reason or "수동 제어",
        "valveAction": valve_action,
        "duration": 30 if valve_action == "열림" else 0,
        "autoTriggered": False,
    }
    irrigation_events.append(event)
    return event
