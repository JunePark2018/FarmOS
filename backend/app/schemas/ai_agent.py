"""AI Agent Pydantic 스키마."""

from pydantic import BaseModel, Field


class NutrientRatio(BaseModel):
    N: float = 1.0
    P: float = 1.0
    K: float = 1.0


class CropProfileIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, examples=["토마토"])
    growth_stage: str = Field(..., examples=["개화기"])
    optimal_temp: list[float] = Field(default=[20, 28], min_length=2, max_length=2)
    optimal_humidity: list[float] = Field(default=[60, 80], min_length=2, max_length=2)
    optimal_light_hours: float = Field(default=14, ge=0, le=24)
    nutrient_ratio: NutrientRatio = Field(default_factory=NutrientRatio)


class OverrideIn(BaseModel):
    control_type: str = Field(..., pattern="^(ventilation|irrigation|lighting|shading)$")
    values: dict
    reason: str = Field(default="수동 제어")
