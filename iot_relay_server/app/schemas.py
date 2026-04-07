from datetime import datetime

from pydantic import BaseModel, Field


class SensorValues(BaseModel):
    temperature: float = Field(ge=-40, le=80)
    humidity: float = Field(ge=0, le=100)
    light_intensity: int = Field(ge=0, le=100000)
    soil_moisture: float | None = Field(default=None, ge=0, le=100)


class SensorDataIn(BaseModel):
    device_id: str
    timestamp: datetime | None = None
    sensors: SensorValues


class IrrigationTriggerIn(BaseModel):
    valve_action: str = Field(pattern=r"^(열림|닫힘)$")
    reason: str = ""
