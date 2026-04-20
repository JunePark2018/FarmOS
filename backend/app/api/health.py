from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.store import get_counts

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)) -> dict:
    """서버 상태 및 IoT 테이블 건수."""
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    counts = await get_counts(db) if db_ok else {
        "readings_count": 0,
        "irrigation_events_count": 0,
        "alerts_count": 0,
    }

    return {
        "status": "ok" if db_ok else "degraded",
        "storage": "postgres",
        **counts,
    }
