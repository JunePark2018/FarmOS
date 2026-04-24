"""번들 농약 JSON → PostgreSQL 자동 시드.

부팅 시 VERSION 비교 후 필요할 때만 bootstrap/pesticide.py 를 subprocess 로 호출.
서버 응답을 막지 않도록 백그라운드 태스크로 실행한다.
"""

import asyncio
import logging
import subprocess
import sys
from pathlib import Path

from sqlalchemy import select

from app.core.database import async_session
from app.models.pesticide import PesticideDataVersion

logger = logging.getLogger(__name__)

# backend/app/core/pesticide_autoseed.py  →  backend/
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
DATA_DIR = BACKEND_DIR / "data" / "pesticide"
JSON_DIR = DATA_DIR / "json_raw"
VERSION_FILE = DATA_DIR / "VERSION.txt"
BOOTSTRAP_SCRIPT = PROJECT_ROOT / "bootstrap" / "pesticide.py"


def _read_bundled_version() -> str | None:
    if not VERSION_FILE.exists():
        return None
    value = VERSION_FILE.read_text(encoding="utf-8").strip()
    return value or None


async def _get_db_version() -> str | None:
    async with async_session() as db:
        stmt = (
            select(PesticideDataVersion)
            .order_by(PesticideDataVersion.id.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        row = result.scalar_one_or_none()
        return row.version if row else None


async def _record_seed(version: str) -> None:
    async with async_session() as db:
        db.add(PesticideDataVersion(version=version))
        await db.commit()


def _run_bootstrap_sync() -> tuple[int, str]:
    """bootstrap/pesticide.py 를 동기 subprocess 로 실행.

    Windows 의 asyncio SelectorEventLoop 는 subprocess 를 지원하지 않으므로
    to_thread 로 감싸 호출하는 용도.
    """
    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(BOOTSTRAP_SCRIPT),
                "--input-dir",
                str(JSON_DIR),
                "--append",
            ],
            cwd=str(BACKEND_DIR),
            capture_output=True,
            timeout=600,
        )
        stderr = (proc.stderr or b"").decode("utf-8", errors="replace")
        return proc.returncode, stderr
    except subprocess.TimeoutExpired:
        return -1, "bootstrap timeout (600s)"


async def _run_bootstrap() -> bool:
    if not BOOTSTRAP_SCRIPT.exists():
        logger.warning("bootstrap/pesticide.py 가 없어 자동 시드를 건너뜁니다.")
        return False
    if not JSON_DIR.exists() or not any(JSON_DIR.rglob("*.json*")):
        logger.warning(f"번들 JSON 이 없어 자동 시드를 건너뜁니다: {JSON_DIR}")
        return False

    returncode, stderr = await asyncio.to_thread(_run_bootstrap_sync)
    if returncode == 0:
        logger.info("농약 DB 자동 시드 성공")
        return True
    logger.error(f"농약 DB 자동 시드 실패 (exit={returncode}): {stderr[-800:]}")
    return False


async def _autoseed_task() -> None:
    try:
        bundled = _read_bundled_version()
        if bundled is None:
            logger.info("번들 VERSION.txt 가 없어 농약 DB 자동 시드를 건너뜁니다.")
            return
        db_version = await _get_db_version()
        if bundled == db_version:
            logger.info(f"농약 DB 버전 최신 ({bundled}), 자동 시드 건너뜀")
            return
        logger.info(f"농약 DB 자동 시드 시작: bundled={bundled}, db={db_version}")
        if await _run_bootstrap():
            await _record_seed(bundled)
            logger.info(f"농약 DB 버전 기록 완료: {bundled}")
    except Exception:
        logger.exception("농약 DB 자동 시드 중 예외 발생")


def schedule_pesticide_autoseed() -> None:
    """lifespan 에서 fire-and-forget 으로 호출.

    서버 응답은 즉시 가능하고, pesticide_matcher 는 빈 DB 에서도 graceful 동작하므로
    시드가 완료되기 전 요청이 와도 기능은 유지된다 (매칭 정확도만 낮을 뿐).
    """
    asyncio.create_task(_autoseed_task())
