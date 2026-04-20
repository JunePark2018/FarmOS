"""IoT 센서·관수·알림 영속 모델. `iot_` 접두사 3개 테이블."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _uuid_str() -> str:
    return str(uuid4())


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class IotSensorReading(Base):
    __tablename__ = "iot_sensor_readings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    soil_moisture: Mapped[float] = mapped_column(Float, nullable=False)
    temperature: Mapped[float] = mapped_column(Float, nullable=False)
    humidity: Mapped[float] = mapped_column(Float, nullable=False)
    light_intensity: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now_utc
    )

    __table_args__ = (
        Index("ix_iot_sensor_readings_timestamp_desc", "timestamp"),
    )


class IotIrrigationEvent(Base):
    __tablename__ = "iot_irrigation_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    valve_action: Mapped[str] = mapped_column(String(10), nullable=False)
    duration: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    auto_triggered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now_utc
    )


class IotSensorAlert(Base):
    __tablename__ = "iot_sensor_alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(String(255), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now_utc
    )
