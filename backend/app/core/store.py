"""IoT 센서 데이터 PostgreSQL 저장소. `iot_sensor_readings` / `iot_irrigation_events` / `iot_sensor_alerts` 3 테이블 사용."""

import random
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.iot import IotIrrigationEvent, IotSensorAlert, IotSensorReading

# 토양 습도 추정용 시간 관성 상태 (프로세스 스코프, 영속화 대상 아님)
_prev_soil_moisture: float | None = None


def _estimate_soil_moisture(
    temperature: float, humidity: float, light_intensity: float
) -> float:
    """온도·대기 습도·조도를 기반으로 토양 습도를 추정한다.

    원리:
      - 기본 보유 수분 55%
      - 대기 습도 ↑ → 증발 억제 → 토양 습도 ↑
      - 온도/조도 ↑ → 증발 증가 → 토양 습도 ↓
      - 시간 관성 (이전 값 70% + 새 추정값 30%)
    """
    global _prev_soil_moisture

    base = 55.0
    humidity_effect = (humidity - 50) * 0.3
    temp_effect = (temperature - 20) * 0.4
    light_effect = (light_intensity / 100) * 2

    estimated = base + humidity_effect - temp_effect - light_effect
    estimated += random.uniform(-2.0, 2.0)

    if _prev_soil_moisture is not None:
        estimated = _prev_soil_moisture * 0.7 + estimated * 0.3

    estimated = max(20.0, min(85.0, estimated))
    _prev_soil_moisture = estimated
    return round(estimated, 1)


def _reading_to_dict(row: IotSensorReading) -> dict:
    return {
        "device_id": row.device_id,
        "timestamp": row.timestamp.isoformat(),
        "soilMoisture": row.soil_moisture,
        "temperature": row.temperature,
        "humidity": row.humidity,
        "lightIntensity": row.light_intensity,
    }


def _alert_to_dict(row: IotSensorAlert) -> dict:
    return {
        "id": row.id,
        "type": row.type,
        "severity": row.severity,
        "message": row.message,
        "timestamp": row.timestamp.isoformat(),
        "resolved": row.resolved,
    }


def _event_to_dict(row: IotIrrigationEvent) -> dict:
    return {
        "id": row.id,
        "triggeredAt": row.triggered_at.isoformat(),
        "reason": row.reason,
        "valveAction": row.valve_action,
        "duration": row.duration,
        "autoTriggered": row.auto_triggered,
    }


async def add_reading(
    db: AsyncSession,
    device_id: str,
    sensors: dict,
    timestamp: datetime | None = None,
) -> list[dict]:
    """센서 데이터를 저장하고, 임계값 초과 시 알림/관개 이벤트를 자동 생성한다."""
    ts = timestamp or datetime.now(timezone.utc)

    soil_moisture = sensors.get("soil_moisture")
    if soil_moisture is None:
        soil_moisture = _estimate_soil_moisture(
            temperature=sensors["temperature"],
            humidity=sensors["humidity"],
            light_intensity=sensors["light_intensity"],
        )

    reading = IotSensorReading(
        device_id=device_id,
        timestamp=ts,
        soil_moisture=soil_moisture,
        temperature=sensors["temperature"],
        humidity=sensors["humidity"],
        light_intensity=sensors["light_intensity"],
    )
    db.add(reading)

    new_alerts: list[dict] = []

    if soil_moisture < settings.SOIL_MOISTURE_LOW:
        alert = IotSensorAlert(
            type="moisture",
            severity="경고",
            message=f"토양 습도가 {soil_moisture}%로 임계값 이하입니다",
            timestamp=ts,
            resolved=False,
        )
        db.add(alert)
        db.add(
            IotIrrigationEvent(
                triggered_at=ts,
                reason=f"토양 습도 {soil_moisture}% — 임계값({settings.SOIL_MOISTURE_LOW}%) 이하",
                valve_action="열림",
                duration=30,
                auto_triggered=True,
            )
        )
        await db.flush()
        new_alerts.append(_alert_to_dict(alert))

    if sensors["humidity"] > 90:
        alert = IotSensorAlert(
            type="humidity",
            severity="주의",
            message=f"대기 습도 {sensors['humidity']}%. 병해 발생 위험 증가",
            timestamp=ts,
            resolved=False,
        )
        db.add(alert)
        await db.flush()
        new_alerts.append(_alert_to_dict(alert))

    await db.commit()
    return new_alerts


async def get_latest(db: AsyncSession) -> dict | None:
    """최신 센서 값 1건."""
    stmt = select(IotSensorReading).order_by(desc(IotSensorReading.timestamp)).limit(1)
    row = (await db.execute(stmt)).scalar_one_or_none()
    return _reading_to_dict(row) if row else None


async def get_history(db: AsyncSession, limit: int = 300) -> list[dict]:
    """최근 센서 데이터 목록 (시간순 오름차순)."""
    stmt = (
        select(IotSensorReading)
        .order_by(desc(IotSensorReading.timestamp))
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    items = [_reading_to_dict(r) for r in rows]
    items.reverse()
    return items


async def get_alerts(db: AsyncSession, resolved: bool | None = None) -> list[dict]:
    """알림 목록 (최신순)."""
    stmt = select(IotSensorAlert).order_by(desc(IotSensorAlert.timestamp))
    if resolved is not None:
        stmt = stmt.where(IotSensorAlert.resolved == resolved)
    rows = (await db.execute(stmt)).scalars().all()
    return [_alert_to_dict(r) for r in rows]


async def resolve_alert(db: AsyncSession, alert_id: str) -> bool:
    """알림 해결 처리."""
    stmt = (
        update(IotSensorAlert)
        .where(IotSensorAlert.id == alert_id)
        .values(resolved=True, resolved_at=datetime.now(timezone.utc))
    )
    result = await db.execute(stmt)
    await db.commit()
    return (result.rowcount or 0) > 0


async def get_irrigation_events(db: AsyncSession) -> list[dict]:
    """관개 이력 (최신순)."""
    stmt = select(IotIrrigationEvent).order_by(desc(IotIrrigationEvent.triggered_at))
    rows = (await db.execute(stmt)).scalars().all()
    return [_event_to_dict(r) for r in rows]


async def add_irrigation_event(
    db: AsyncSession, valve_action: str, reason: str
) -> dict:
    """수동 관개 이벤트 추가."""
    now = datetime.now(timezone.utc)
    event = IotIrrigationEvent(
        id=str(uuid4()),
        triggered_at=now,
        reason=reason or "수동 제어",
        valve_action=valve_action,
        duration=30 if valve_action == "열림" else 0,
        auto_triggered=False,
    )
    db.add(event)
    await db.commit()
    return _event_to_dict(event)


async def get_counts(db: AsyncSession) -> dict:
    """/health 용 테이블 건수."""
    readings = await db.scalar(
        select(func.count()).select_from(IotSensorReading)
    )
    events = await db.scalar(
        select(func.count()).select_from(IotIrrigationEvent)
    )
    alerts = await db.scalar(
        select(func.count()).select_from(IotSensorAlert)
    )
    return {
        "readings_count": int(readings or 0),
        "irrigation_events_count": int(events or 0),
        "alerts_count": int(alerts or 0),
    }
