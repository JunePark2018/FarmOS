"""Upstage Document Parse를 이용한 시행지침 PDF → Markdown 변환.

Upstage Document Parse는 한국 정부 문서 처리에 특화된 API로,
PDF/HWP를 Markdown으로 변환하며 표·레이아웃·읽기 순서를 정확히 보존합니다.

파이프라인에서의 위치:
    [PDF] → Upstage Parse → [Markdown 캐시] → chunker.py → ChromaDB
            (이 파일)       (재사용 가능)

비용:
    Parse는 페이지당 약 $0.01 — 150쪽 시행지침 1회 약 $1.50.
    Markdown 캐시가 존재하면 재파싱을 건너뜀 (기본 동작).

사용:
    # 서버 시작 없이 스크립트로 직접 실행
    $ cd backend
    $ uv run python -m app.services.subsidy.pdf_ingest

    # 또는 파이썬 코드에서:
    from app.services.subsidy.pdf_ingest import parse_subsidy_pdf
    markdown = await parse_subsidy_pdf()
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from langchain_upstage import UpstageDocumentParseLoader

from app.core.config import settings

logger = logging.getLogger(__name__)


class UpstageApiKeyMissing(RuntimeError):
    """UPSTAGE_API_KEY가 설정되지 않았을 때."""


def _resolve_paths() -> tuple[Path, Path]:
    """PDF 입력 경로와 Markdown 캐시 경로를 절대 경로로 반환."""
    # backend/ 디렉터리 기준으로 상대경로가 적용됨
    base = Path(__file__).resolve().parents[3]  # .../backend
    pdf_path = base / settings.SUBSIDY_PDF_PATH
    md_path = base / settings.SUBSIDY_MARKDOWN_CACHE_PATH
    return pdf_path, md_path


async def parse_subsidy_pdf(force: bool = False) -> str:
    """시행지침 PDF를 Upstage로 파싱하고 Markdown 문자열을 반환한다.

    Args:
        force: True이면 캐시 무시하고 재파싱

    Returns:
        전체 Markdown 문자열

    Raises:
        UpstageApiKeyMissing: API 키 미설정
        FileNotFoundError: PDF 파일 없음
    """
    pdf_path, md_path = _resolve_paths()

    if not pdf_path.exists():
        raise FileNotFoundError(f"시행지침 PDF를 찾을 수 없습니다: {pdf_path}")

    # 캐시 재사용
    if md_path.exists() and not force:
        logger.info(f"Markdown 캐시 사용: {md_path}")
        return md_path.read_text(encoding="utf-8")

    if not settings.UPSTAGE_API_KEY:
        raise UpstageApiKeyMissing(
            "UPSTAGE_API_KEY가 설정되지 않았습니다. "
            ".env 파일에 키를 추가하세요 (https://console.upstage.ai)."
        )

    logger.info(f"Upstage Document Parse 호출 시작: {pdf_path.name}")

    # LangChain Upstage 로더는 동기 API이므로 별도 스레드에서 실행
    loader = UpstageDocumentParseLoader(
        file_path=str(pdf_path),
        api_key=settings.UPSTAGE_API_KEY,
        output_format="markdown",
        split="page",          # 페이지 단위 Document로 분리 (메타데이터 활용)
        ocr="auto",            # 필요 시 OCR 자동 적용
        coordinates=False,     # 좌표 불필요
    )

    documents = await asyncio.to_thread(loader.load)
    logger.info(f"Upstage 파싱 완료: {len(documents)}개 페이지")

    # 페이지 구분자와 함께 하나의 Markdown으로 병합
    parts: list[str] = []
    for doc in documents:
        page_num = doc.metadata.get("page", "?")
        parts.append(f"<!-- page:{page_num} -->\n{doc.page_content}")
    full_markdown = "\n\n".join(parts)

    # 캐시 저장
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(full_markdown, encoding="utf-8")
    logger.info(f"Markdown 캐시 저장: {md_path} ({len(full_markdown):,} chars)")

    return full_markdown


def _cli_main() -> None:
    """PDF → Markdown 초기 파싱 CLI 엔트리포인트.

    사용 (둘 중 하나):
        uv run subsidy-parse-pdf
        uv run python -m app.services.subsidy.pdf_ingest
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    md = asyncio.run(parse_subsidy_pdf(force=False))
    logger.info(f"파싱 완료: {len(md):,} chars → {settings.SUBSIDY_MARKDOWN_CACHE_PATH}")


if __name__ == "__main__":
    _cli_main()
