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


class NutrientRatio(BaseModel):
    N: float = 1.0
    P: float = 1.0
    K: float = 1.0


class CropProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    growth_stage: str
    optimal_temp: list[float] = Field(default=[20, 28], min_length=2, max_length=2)
    optimal_humidity: list[float] = Field(default=[60, 80], min_length=2, max_length=2)
    optimal_light_hours: float = Field(default=14, ge=0, le=24)
    nutrient_ratio: NutrientRatio = Field(default_factory=NutrientRatio)


class OverrideIn(BaseModel):
    control_type: str = Field(pattern=r"^(ventilation|irrigation|lighting|shading)$")
    values: dict
    reason: str = "수동 제어"
