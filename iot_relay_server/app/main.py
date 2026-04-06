from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader

from app.config import settings
from app.schemas import SensorDataIn, IrrigationTriggerIn
from app.store import (
    add_reading,
    get_alerts,
    get_history,
    get_irrigation_events,
    get_latest,
    resolve_alert,
    add_irrigation_event,
)

app = FastAPI(title="FarmOS IoT Relay Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str | None = Depends(_api_key_header)) -> str:
    if not api_key or api_key != settings.IOT_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="유효하지 않은 API Key입니다.",
        )
    return api_key


# --- Health ---

@app.get("/health")
async def health():
    return {"status": "ok"}


# --- Sensors ---

sensors_router = APIRouter(prefix="/api/v1/sensors", tags=["sensors"])


@sensors_router.post("", status_code=201, dependencies=[Depends(verify_api_key)])
async def receive_sensor_data(data: SensorDataIn) -> dict:
    new_alerts = add_reading(
        device_id=data.device_id,
        sensors=data.sensors.model_dump(),
        timestamp=data.timestamp,
    )
    return {"status": "ok", "alerts_generated": len(new_alerts)}


@sensors_router.get("/latest")
async def latest_reading() -> dict:
    reading = get_latest()
    if reading is None:
        return {"timestamp": None, "soilMoisture": 0, "temperature": 0, "humidity": 0, "lightIntensity": 0}
    return reading


@sensors_router.get("/history")
async def sensor_history(limit: int = Query(default=300, ge=1, le=2000)) -> list[dict]:
    return get_history(limit)


@sensors_router.get("/alerts")
async def sensor_alerts(resolved: bool | None = None) -> list[dict]:
    return get_alerts(resolved)


@sensors_router.patch("/alerts/{alert_id}/resolve")
async def resolve_sensor_alert(alert_id: str) -> dict:
    if resolve_alert(alert_id):
        return {"status": "resolved"}
    return {"error": "alert not found"}


# --- Irrigation ---

irrigation_router = APIRouter(prefix="/api/v1/irrigation", tags=["irrigation"])


@irrigation_router.post("/trigger")
async def trigger_irrigation(data: IrrigationTriggerIn) -> dict:
    event = add_irrigation_event(data.valve_action, data.reason)
    return event


@irrigation_router.get("/events")
async def irrigation_events() -> list[dict]:
    return get_irrigation_events()


# --- Register routers ---

app.include_router(sensors_router)
app.include_router(irrigation_router)
