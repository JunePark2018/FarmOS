"""AI Agent REST API 엔드포인트."""

from fastapi import APIRouter, Depends, Query

from app.core.deps import get_current_user
from app.core import ai_agent
from app.schemas.ai_agent import CropProfileIn, OverrideIn

router = APIRouter(prefix="/ai-agent", tags=["ai-agent"])


@router.get("/status", dependencies=[Depends(get_current_user)])
async def get_agent_status() -> dict:
    """AI Agent 현재 상태 (활성 여부 + 제어 상태 + 최신 판단)."""
    return ai_agent.get_status()


@router.get("/decisions", dependencies=[Depends(get_current_user)])
async def get_agent_decisions(limit: int = Query(default=20, ge=1, le=500)) -> list[dict]:
    """AI Agent 판단 이력."""
    return ai_agent.get_decisions(limit)


@router.post("/toggle", dependencies=[Depends(get_current_user)])
async def toggle_agent() -> dict:
    """AI Agent ON/OFF 토글."""
    enabled = ai_agent.toggle_agent()
    return {"enabled": enabled}


@router.get("/crop-profile", dependencies=[Depends(get_current_user)])
async def get_crop_profile() -> dict:
    """현재 작물 프로필 조회."""
    return {
        "profile": ai_agent.crop_profile,
        "presets": ai_agent.get_crop_presets(),
    }


@router.put("/crop-profile", dependencies=[Depends(get_current_user)])
async def update_crop_profile(data: CropProfileIn) -> dict:
    """작물 프로필 수정."""
    profile = ai_agent.update_crop_profile(data.model_dump())
    return {"profile": profile}


@router.post("/override", dependencies=[Depends(get_current_user)])
async def override_control(data: OverrideIn) -> dict:
    """수동 오버라이드 (특정 제어 항목 직접 설정)."""
    decision = ai_agent.override_control(data.control_type, data.values, data.reason)
    return {"decision": decision}
