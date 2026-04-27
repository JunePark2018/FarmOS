"""백엔드 API 에서 트리거되는 농약 크롤러 + 번들 갱신 서비스.

흐름:
1. 사용자가 POST /pesticide/crawl 호출
2. 백그라운드로 tools/pesticide-api-crawler/pesticide-crawler.py 실행 (~1시간)
3. 크롤링 완료 후 결과 JSON 을 gzip 압축해 backend/data/pesticide/json_raw/ 에 배치
4. backend/data/pesticide/VERSION.txt 갱신
5. 다음 서버 재부팅 시 pesticide_autoseed 가 새 VERSION 감지해 PostgreSQL 재시드

자동 크롤링은 일절 없음. 반드시 명시적 API 호출이 있어야만 동작한다.
"""

import asyncio
import gzip
import json
import logging
import shutil
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# 경로 상수
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
CRAWLER_DIR = PROJECT_ROOT / "tools" / "pesticide-api-crawler"
CRAWLER_SCRIPT = CRAWLER_DIR / "pesticide-crawler.py"
CRAWLER_OUTPUT_DIR = CRAWLER_DIR / "json_raw"
BUNDLE_DIR = BACKEND_DIR / "data" / "pesticide"
BUNDLE_JSON_DIR = BUNDLE_DIR / "json_raw"
BUNDLE_VERSION_FILE = BUNDLE_DIR / "VERSION.txt"

# 크롤 타임아웃 (1시간 30분 = 안전 마진)
CRAWL_TIMEOUT_SEC = 5400

# 동시 실행 방지 + 상태 추적
_state_lock = asyncio.Lock()
_state: dict = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "phase": None,  # "crawling" | "bundling" | "done" | "failed"
    "returncode": None,
    "error_tail": None,
    "result": None,  # {"new_files", "total_rows", "version"}
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check_prereqs() -> str | None:
    """사전 조건 점검. 문제 있으면 사유 메시지 반환, 없으면 None."""
    if not CRAWLER_SCRIPT.exists():
        return f"크롤러 스크립트 없음: {CRAWLER_SCRIPT}"
    if shutil.which("uv") is None:
        return "uv 명령을 찾을 수 없음 (uv 설치 필요: https://github.com/astral-sh/uv)"
    return None


def _run_crawler_sync() -> tuple[int, str]:
    """크롤러 subprocess 동기 실행. (returncode, stderr_tail) 반환.

    크롤러는 자체 .venv 의존성이 있어 sys.executable 대신 `uv run` 사용.
    progress.json 덕에 중단/재개 가능 — 매 호출마다 이어 받음.
    """
    try:
        proc = subprocess.run(
            ["uv", "run", "python", "pesticide-crawler.py", "--delay-seconds", "60"],
            cwd=str(CRAWLER_DIR),
            capture_output=True,
            timeout=CRAWL_TIMEOUT_SEC,
        )
        stderr_tail = (proc.stderr or b"").decode("utf-8", errors="replace")[-1500:]
        return proc.returncode, stderr_tail
    except subprocess.TimeoutExpired:
        return -1, f"crawler timeout ({CRAWL_TIMEOUT_SEC}s)"


def _bundle_gzip_sync() -> dict:
    """크롤러 결과 .json 을 gzip 압축해 번들 디렉토리에 배치 + VERSION.txt 갱신.

    기존 .gz 는 모두 제거하고 새로 생성 (전체 갱신 정책).
    """
    BUNDLE_JSON_DIR.mkdir(parents=True, exist_ok=True)

    # 기존 .gz 모두 제거
    for old in BUNDLE_JSON_DIR.glob("*.json.gz"):
        old.unlink()

    new_files = 0
    total_rows = 0
    for src in sorted(CRAWLER_OUTPUT_DIR.glob("*.json")):
        dst = BUNDLE_JSON_DIR / f"{src.name}.gz"
        with open(src, "rb") as r, gzip.open(dst, "wb", compresslevel=9) as w:
            shutil.copyfileobj(r, w)
        new_files += 1
        try:
            with gzip.open(dst, "rt", encoding="utf-8") as f:
                payload = json.load(f)
            rows = payload.get("I1910", {}).get("row", []) or []
            total_rows += len(rows)
        except Exception:
            # row 카운트 실패해도 파이프라인 계속 진행
            logger.warning(f"row count 실패: {dst.name}")

    version = f"{date.today().isoformat()}_{total_rows}"
    BUNDLE_VERSION_FILE.write_text(version, encoding="utf-8")
    return {"new_files": new_files, "total_rows": total_rows, "version": version}


async def _run_crawl_pipeline() -> None:
    """크롤링 → 번들링 전체 파이프라인 (백그라운드 태스크)."""
    try:
        # Phase 1: 크롤링
        _state["phase"] = "crawling"
        logger.info("농약 크롤링 시작 (백그라운드, 약 1시간 소요)")
        returncode, stderr_tail = await asyncio.to_thread(_run_crawler_sync)
        _state["returncode"] = returncode

        if returncode != 0:
            _state["phase"] = "failed"
            _state["error_tail"] = stderr_tail
            logger.error(f"농약 크롤링 실패 (exit={returncode}): {stderr_tail[-500:]}")
            return

        # Phase 2: 번들 갱신
        _state["phase"] = "bundling"
        logger.info("크롤링 완료 — gzip 번들 갱신 시작")
        result = await asyncio.to_thread(_bundle_gzip_sync)
        _state["result"] = result
        _state["phase"] = "done"
        logger.info(
            f"농약 번들 갱신 완료: files={result['new_files']} "
            f"rows={result['total_rows']} version={result['version']} "
            f"(다음 서버 재시작 시 autoseed 가 자동 적재)"
        )
    except Exception as e:
        logger.exception("농약 크롤 파이프라인 예외")
        _state["phase"] = "failed"
        _state["error_tail"] = str(e)
    finally:
        _state["finished_at"] = _now_iso()
        _state["running"] = False


async def trigger_crawl() -> dict:
    """크롤 트리거. 이미 진행 중이거나 사전 조건 미충족이면 사유 반환.

    Returns:
        {"started": True, "started_at": "..."} 또는
        {"started": False, "reason": "...", ...}
    """
    err = _check_prereqs()
    if err:
        return {"started": False, "reason": "prerequisite_failed", "detail": err}

    async with _state_lock:
        if _state["running"]:
            return {
                "started": False,
                "reason": "already_running",
                "started_at": _state.get("started_at"),
                "phase": _state.get("phase"),
            }

        _state.update({
            "running": True,
            "started_at": _now_iso(),
            "finished_at": None,
            "phase": "crawling",
            "returncode": None,
            "error_tail": None,
            "result": None,
        })

    asyncio.create_task(_run_crawl_pipeline())
    return {"started": True, "started_at": _state["started_at"]}


def get_crawl_status() -> dict:
    """현재 크롤 상태 스냅샷."""
    return dict(_state)
