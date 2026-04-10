import asyncio

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from starlette.responses import StreamingResponse

from app.config import settings
from app.schemas import SensorDataIn, IrrigationTriggerIn, CropProfileIn, OverrideIn
from app.store import (
    add_reading,
    get_alerts,
    get_history,
    get_irrigation_events,
    get_latest,
    resolve_alert,
    add_irrigation_event,
    sse_subscribe,
    sse_unsubscribe,
)
from app import ai_agent

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
    sensors_dict = data.sensors.model_dump()
    new_alerts = add_reading(
        device_id=data.device_id,
        sensors=sensors_dict,
        timestamp=data.timestamp,
    )

    # AI Agent에 센서 데이터 전달 — store.py에서 추정한 토양습도를 반영
    import logging
    try:
        latest = get_latest()
        if latest:
            sensors_for_agent = {
                "temperature": latest["temperature"],
                "humidity": latest["humidity"],
                "light_intensity": latest["lightIntensity"],
                "soil_moisture": latest["soilMoisture"],
            }
            await ai_agent.process_sensor_data(sensors_for_agent)
    except Exception as e:
        logging.getLogger("ai_agent").error("AI Agent 처리 실패: %s", e, exc_info=True)

    return {"status": "ok", "alerts_generated": len(new_alerts)}


@sensors_router.get("/stream")
async def sensor_stream(request: Request):
    """SSE 스트림 — 센서/알림/관수 이벤트를 실시간 push."""
    queue = sse_subscribe()

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30)
                    yield msg
                except asyncio.TimeoutError:
                    # keep-alive
                    yield ": heartbeat\n\n"
        finally:
            sse_unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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


# --- AI Agent ---

agent_router = APIRouter(prefix="/api/v1/ai-agent", tags=["ai-agent"])


@agent_router.get("/status")
async def agent_status() -> dict:
    return ai_agent.get_status()


@agent_router.get("/decisions")
async def agent_decisions(limit: int = Query(default=20, ge=1, le=500)) -> list[dict]:
    return ai_agent.get_decisions(limit)


@agent_router.post("/toggle")
async def agent_toggle() -> dict:
    enabled = ai_agent.toggle_agent()
    return {"enabled": enabled}


@agent_router.get("/crop-profile")
async def get_crop_profile() -> dict:
    return {"profile": ai_agent.crop_profile, "presets": ai_agent.get_crop_presets()}


@agent_router.put("/crop-profile")
async def update_crop_profile(data: CropProfileIn) -> dict:
    profile = ai_agent.update_crop_profile(data.model_dump())
    return {"profile": profile}


@agent_router.post("/override")
async def override_control(data: OverrideIn) -> dict:
    decision = ai_agent.override_control(data.control_type, data.values, data.reason)
    return {"decision": decision}


@agent_router.post("/test-trigger")
async def test_trigger() -> dict:
    """디버그: 최신 센서값으로 AI Agent를 수동 트리거."""
    latest = get_latest()
    if not latest:
        return {"error": "센서 데이터 없음"}
    sensors_dict = {
        "temperature": latest["temperature"],
        "humidity": latest["humidity"],
        "light_intensity": latest["lightIntensity"],
        "soil_moisture": latest["soilMoisture"],
    }
    try:
        decisions = await ai_agent.process_sensor_data(sensors_dict)
        return {"decisions": decisions, "agent_enabled": ai_agent.agent_enabled}
    except Exception as e:
        return {"error": str(e), "type": type(e).__name__}


# --- Register routers ---

app.include_router(sensors_router)
app.include_router(irrigation_router)
app.include_router(agent_router)
