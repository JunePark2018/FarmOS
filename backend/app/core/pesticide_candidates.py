"""Whisper/LLM 힌트용 농약 후보 선정 — 작물별 + 전역 빈도 하이브리드."""

import time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.journal import JournalEntry
from app.models.pesticide import PesticideProduct

_CACHE_TTL_SEC = 600
_cache: dict[str, tuple[float, list[str]]] = {}


def _cache_get(key: str) -> list[str] | None:
    entry = _cache.get(key)
    if not entry:
        return None
    ts, value = entry
    if time.time() - ts > _CACHE_TTL_SEC:
        _cache.pop(key, None)
        return None
    return value


def _cache_set(key: str, value: list[str]) -> None:
    _cache[key] = (time.time(), value)


async def get_frequent_pesticides(
    db: AsyncSession,
    limit: int = 30,
    user_id: str | None = None,
) -> list[str]:
    """journal_entries에서 사용 빈도가 높은 농약명을 추출.

    user_id가 있으면 해당 사용자 기록만, 없으면 전체 사용자 집계.
    """
    cache_key = f"freq:{user_id or '_all_'}:{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    stmt = (
        select(
            JournalEntry.usage_pesticide_product,
            func.count(JournalEntry.id).label("cnt"),
        )
        .where(JournalEntry.usage_pesticide_product.isnot(None))
        .where(JournalEntry.usage_pesticide_product != "")
        .group_by(JournalEntry.usage_pesticide_product)
        .order_by(func.count(JournalEntry.id).desc())
        .limit(limit)
    )
    if user_id:
        stmt = stmt.where(JournalEntry.user_id == user_id)

    result = await db.execute(stmt)
    names = [row[0] for row in result.all() if row[0]]
    _cache_set(cache_key, names)
    return names


async def get_crop_pesticides(
    db: AsyncSession,
    crop: str,
    limit: int = 30,
) -> list[str]:
    """rag_pesticide_documents에서 작물별 등록 농약을 문서 수 순으로 추출."""
    if not crop or not crop.strip():
        return []

    crop = crop.strip()
    cache_key = f"crop:{crop}:{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    stmt = (
        select(
            PesticideProduct.ingredient_or_formulation_name,
            func.count(PesticideProduct.document_id).label("cnt"),
        )
        .where(PesticideProduct.crop_name == crop)
        .where(PesticideProduct.ingredient_or_formulation_name.isnot(None))
        .group_by(PesticideProduct.ingredient_or_formulation_name)
        .order_by(func.count(PesticideProduct.document_id).desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    names = [row[0] for row in result.all() if row[0]]
    _cache_set(cache_key, names)
    return names


async def _build_tiered_candidates(
    db: AsyncSession,
    crop: str | None,
    top_n: int,
    user_id: str | None,
) -> list[str]:
    """1순위: 작물별, 2순위: 전역 빈도로 채우며 중복 제거."""
    candidates: list[str] = []
    seen: set[str] = set()

    if crop:
        for name in await get_crop_pesticides(db, crop, limit=top_n):
            if name not in seen:
                candidates.append(name)
                seen.add(name)

    if len(candidates) < top_n:
        for name in await get_frequent_pesticides(db, limit=top_n, user_id=user_id):
            if name not in seen:
                candidates.append(name)
                seen.add(name)
                if len(candidates) >= top_n:
                    break

    return candidates[:top_n]


async def build_whisper_prompt(
    db: AsyncSession,
    crop: str | None = None,
    top_n: int = 30,
    user_id: str | None = None,
) -> str:
    """Whisper `prompt` 파라미터용 쉼표 구분 농약명 문자열.

    224 토큰 제한을 고려해 top_n을 보수적으로(기본 30) 유지.
    후보가 없으면 빈 문자열 반환.
    """
    names = await _build_tiered_candidates(db, crop, top_n, user_id)
    return ", ".join(names)


async def build_llm_candidates(
    db: AsyncSession,
    crop: str | None = None,
    top_n: int = 80,
    user_id: str | None = None,
) -> list[str]:
    """LLM 파싱 프롬프트 주입용 농약 후보 리스트 (Phase 3용)."""
    return await _build_tiered_candidates(db, crop, top_n, user_id)


def clear_cache() -> None:
    """테스트/수동 새로고침용 캐시 초기화."""
    _cache.clear()
