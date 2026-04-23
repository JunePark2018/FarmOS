"""공익직불 시행지침 RAG — 비대칭 Solar 임베딩 + 리랭커 + 키워드 부스트.

설계 원칙 (Decision 7):
    Dense retrieval (Solar asymmetric) + Cross-encoder rerank + regex keyword boost.
    Korean BM25 (Kiwi/Mecab) 없음 — 섹션 타이틀 기반 부스트로 대체.

파이프라인:
    query
      └─ Solar query embedding (solar-embedding-1-large-query)
         └─ ChromaDB vector search → top 30 후보
            └─ 섹션 타이틀 키워드 부스트 (규칙 기반)
               └─ dragonkue/bge-reranker-v2-m3-ko cross-encoder → top 5
                  └─ 반환 (Citation 객체)

컬렉션 명: "gov_subsidy" (기존 diagnosis/review 컬렉션과 격리)

주의:
    - ChromaDB에 embedding_function을 주입하지 않음 — passage/query 모델이 다르므로
      수동으로 pre-compute하여 embeddings=, query_embeddings= 로 넘김
    - 리랭커는 첫 검색 시 초기화 (약 2초 소요, 이후 캐시)
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import TYPE_CHECKING

from langchain_upstage import UpstageEmbeddings

from app.core.config import settings
from app.core.vectordb import get_client
from app.schemas.subsidy import Citation
from app.services.subsidy.chunker import PLACEHOLDER_SECTION_LABELS

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder

    from app.services.subsidy.chunker import Chunk

logger = logging.getLogger(__name__)

COLLECTION_NAME = "gov_subsidy"

# 섹션 타이틀 기반 부스트 키워드
# 쿼리에 이들 중 하나가 포함되고, 청크의 subsection_title에도 포함되면 부스트
TITLE_BOOST_KEYWORDS: list[str] = [
    "소농직불", "면적직불", "지급대상", "자격요건", "지급단가", "농지",
    "농업인", "부정수급", "농업경영체", "진흥지역", "역전구간",
    "재배면적", "준수사항", "농약", "화학비료", "교육", "영농폐기물",
    "영농기록", "농업·농촌", "공익기능", "행정처분", "감액지급",
    "정보화", "검증", "보조금", "지도", "감독",
]

TITLE_BOOST_SCORE = 0.08   # 1등급 유사도 약 0.7~0.9 대비 약 10% 가산
RERANKER_CANDIDATES = 15   # 재랭킹에 넘길 후보 수
DEFAULT_TOP_K = 5

# Solar Embedding은 4000 토큰 제한. 한글은 약 0.4 tok/char → ~10,000 char 상한이지만
# prefix + 안전마진 고려해 6,000자로 split. 의미 손실 최소화 위해 자연 경계(빈 줄)에서 분할.
MAX_EMBED_CHARS = 6_000


class GovSubsidyRAG:
    """공익직불 시행지침 RAG 서비스.

    사용 예:
        rag = GovSubsidyRAG()
        added = rag.index_chunks(chunks)       # 초기 1회
        hits = rag.search("소농직불금 자격이 뭐야?", top_k=5)
    """

    def __init__(self) -> None:
        if not settings.UPSTAGE_API_KEY:
            raise RuntimeError(
                "UPSTAGE_API_KEY가 설정되지 않았습니다. "
                ".env 파일에 키를 추가하세요 (https://console.upstage.ai)."
            )

        self.embeddings = UpstageEmbeddings(
            api_key=settings.UPSTAGE_API_KEY,
            model="solar-embedding-1-large",
        )
        # 빈 컬렉션으로 획득 (embedding_function 미주입 — 수동 pre-compute)
        client = get_client()
        self.collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    # ── 인덱싱 ──────────────────────────────────────────────

    def index_chunks(self, chunks: list["Chunk"], skip_existing: bool = True) -> int:
        """청크를 ChromaDB에 임베딩 저장한다.

        Args:
            chunks: chunker.build_chunks() 결과
            skip_existing: True면 이미 저장된 id는 건너뜀

        Returns:
            새로 추가된 청크 수
        """
        if not chunks:
            return 0

        existing_ids: set[str] = set()
        if skip_existing:
            got = self.collection.get()
            if got and got["ids"]:
                existing_ids = set(got["ids"])

        new_chunks = [c for c in chunks if c.id not in existing_ids]
        if not new_chunks:
            logger.info(f"청크 {len(chunks)}개 모두 인덱스됨, 건너뜀")
            return 0

        # 계층 컨텍스트 prefix — Anthropic contextual retrieval의 경량 버전
        # 임베딩 토큰 제한에 맞춰 큰 청크는 자연 경계에서 분할 (원본 id_partN 형태로 추적)
        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict] = []

        for c in new_chunks:
            prefix = (
                f"[{c.chapter} > {c.section} > {c.subsection}]\n"
                f"이 구절은 {c.subsection_title} 관련 내용입니다.\n\n"
            )
            # 임베딩 토큰 제한 대응 분할
            parts = _split_for_embedding(c.content, MAX_EMBED_CHARS - len(prefix))
            base_meta = {
                "chapter": c.chapter,
                "section": c.section,
                "subsection": c.subsection,
                "subsection_title": c.subsection_title,
                "page_start": c.page_start,
                "page_end": c.page_end,
                "section_type": c.section_type,
            }
            for i, part in enumerate(parts):
                part_id = c.id if len(parts) == 1 else f"{c.id}_p{i}"
                if part_id in existing_ids:
                    continue
                ids.append(part_id)
                documents.append(prefix + part)
                metadatas.append({**base_meta, "parent_id": c.id, "part": i, "part_total": len(parts)})

        if not ids:
            logger.info("인덱싱할 신규 분할 조각이 없습니다")
            return 0

        # Solar passage 임베딩 — embed_documents 내부적으로 -passage 모델 사용
        logger.info(f"Solar passage 임베딩 호출 중 ({len(documents)}건)...")
        vectors = self.embeddings.embed_documents(documents)

        self.collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=vectors,
        )
        logger.info(f"인덱싱 완료: {len(ids)} 조각 추가 (소스 청크 {len(new_chunks)}개 기준, 누적 {self.count()}건)")
        return len(ids)

    # ── 검색 ────────────────────────────────────────────────

    def search(self, query: str, top_k: int = DEFAULT_TOP_K) -> list[Citation]:
        """쿼리에 가장 관련 높은 청크를 Citation 객체 리스트로 반환한다.

        파이프라인:
            1. Solar query 임베딩 (-query 모델)
            2. ChromaDB vector search → top 30
            3. 섹션 타이틀 키워드 부스트
            4. Cross-encoder 재랭킹 → top_k
        """
        if self.count() == 0:
            logger.warning("컬렉션이 비어있음 — 빈 결과 반환")
            return []

        # 1. 쿼리 임베딩
        query_vec = self.embeddings.embed_query(query)

        # 2. 벡터 검색 — 리랭킹 후보 확보 위해 여유있게 3x 가져옴
        n_results = min(RERANKER_CANDIDATES * 2, self.count())
        raw = self.collection.query(
            query_embeddings=[query_vec],
            n_results=n_results,
        )
        candidates = _format_chroma_results(raw)
        if not candidates:
            return []

        # 3. 섹션 타이틀 키워드 부스트
        query_kws = {kw for kw in TITLE_BOOST_KEYWORDS if kw in query}
        if query_kws:
            for c in candidates:
                title = c["metadata"].get("subsection_title", "")
                if any(kw in title for kw in query_kws):
                    c["score"] = round(c["score"] + TITLE_BOOST_SCORE, 4)
            candidates.sort(key=lambda x: x["score"], reverse=True)

        # 4. Cross-encoder 재랭킹
        top_candidates = candidates[:RERANKER_CANDIDATES]
        reranker = _get_reranker()
        pairs = [[query, c["document"]] for c in top_candidates]
        scores = reranker.predict(pairs)

        for c, s in zip(top_candidates, scores, strict=True):
            c["rerank_score"] = float(s)
        top_candidates.sort(key=lambda x: x["rerank_score"], reverse=True)

        # 5. 소단원 중복 제거 (split된 _p0/_p1 파트가 둘 다 top rank인 경우 1개만)
        seen_keys: set[tuple[str, str]] = set()
        unique_hits: list[dict] = []
        for h in top_candidates:
            meta = h["metadata"]
            key = (meta.get("chapter", ""), meta.get("subsection", ""))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            unique_hits.append(h)

        # 6. Citation으로 변환 (컨텍스트 prefix 제거 + 테이블 노이즈 정리)
        hits = unique_hits[:top_k]
        citations: list[Citation] = []
        for h in hits:
            meta = h["metadata"]
            raw = h["document"]
            # 인덱스 prefix 제거 ("[CHAPTER...]\n이 구절은...\n\n" 형태)
            if "\n\n" in raw:
                _, raw = raw.split("\n\n", 1)
            snippet = _clean_snippet_for_display(raw, max_chars=400)

            section = meta.get("section", "") or ""
            # 플레이스홀더 섹션 라벨은 UI 에 노출하지 않음
            # (chunker 내부 구현 디테일 — 단일 source-of-truth 는 chunker 모듈)
            if section in PLACEHOLDER_SECTION_LABELS:
                section = ""
            chapter_path = meta.get("chapter", "")
            if section:
                chapter_path = f"{chapter_path} > {section}"

            citations.append(Citation(
                article=meta.get("subsection", ""),
                chapter=chapter_path,
                snippet=snippet,
                similarity=h["rerank_score"],
            ))
        return citations

    # ── 유틸 ────────────────────────────────────────────────

    def count(self) -> int:
        return self.collection.count()

    def reset(self) -> None:
        """테스트/재인덱싱용 — 컬렉션 전체 삭제."""
        client = get_client()
        try:
            client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass
        self.collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )


# ── 내부 헬퍼 ──────────────────────────────────────────────


def _split_for_embedding(text: str, max_chars: int) -> list[str]:
    """긴 본문을 자연 경계(빈 줄)에서 max_chars 이하로 분할.

    의미 손실 최소화를 위해 빈 줄 > 단일 줄바꿈 > 문자 단위 순으로 시도.
    """
    if len(text) <= max_chars:
        return [text]

    parts: list[str] = []
    # 1차 시도: 빈 줄 단위
    blocks = text.split("\n\n")
    current = ""
    for block in blocks:
        if not block.strip():
            continue
        if len(current) + len(block) + 2 > max_chars and current:
            parts.append(current.strip())
            current = block
        else:
            current = f"{current}\n\n{block}" if current else block
    if current.strip():
        parts.append(current.strip())

    # 여전히 max_chars 초과하는 파트는 줄 단위로 재분할
    final: list[str] = []
    for p in parts:
        if len(p) <= max_chars:
            final.append(p)
            continue
        lines = p.split("\n")
        cur = ""
        for line in lines:
            if len(cur) + len(line) + 1 > max_chars and cur:
                final.append(cur.strip())
                cur = line
            else:
                cur = f"{cur}\n{line}" if cur else line
        if cur.strip():
            final.append(cur.strip())

    # 최후 수단: 문자 단위 강제 분할 (legal text에서는 거의 발생 안 함)
    truly_final: list[str] = []
    for p in final:
        if len(p) <= max_chars:
            truly_final.append(p)
        else:
            for i in range(0, len(p), max_chars):
                truly_final.append(p[i:i + max_chars])
    return truly_final


def _clean_snippet_for_display(text: str, max_chars: int = 400) -> str:
    """RAG citation snippet 을 UI 친화적으로 정리.

    - Markdown 테이블 행(| --- | ... |)을 제거 → 읽기 불가 pipe 노이즈 제거
    - 연속된 공백/줄바꿈을 단일 공백으로 축약
    - 선행 #, 하이픈, 별표 같은 Markdown 헤더·bullet 문자 정리
    - max_chars 로 자르되 가능하면 문장 끝에서 절단
    """
    import re as _re
    # 1) 테이블 구분자 행 제거 (| --- | --- |)
    text = _re.sub(r"\|\s*-{3,}\s*(?:\|\s*-{3,}\s*)+\|", " ", text)
    # 2) 테이블 본체 행을 좀 더 읽기 쉽게: "| a | b | c |" → "a, b, c"
    def _row_to_csv(m: _re.Match[str]) -> str:
        cells = [c.strip() for c in m.group(0).strip("|").split("|") if c.strip()]
        return " · ".join(cells)
    text = _re.sub(r"\|[^|\n]{1,80}(?:\|[^|\n]{1,80})+\|", _row_to_csv, text)
    # 3) Markdown 헤더·불릿·체크박스 문자 정리
    text = _re.sub(r"^#{1,6}\s*", "", text, flags=_re.MULTILINE)
    text = _re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)   # 이미지 placeholder
    text = text.replace("☑", "").replace("□", "")
    # 4) 잔여 pipe 문자 정리 (regex 가 못 잡은 짝 안맞는 | 구분자)
    text = _re.sub(r"\s*\|\s*", " · ", text)
    # 연속된 '·' 중복 제거
    text = _re.sub(r"(?:\s*·\s*){2,}", " · ", text)
    # 5) 공백 축약
    text = _re.sub(r"\s+", " ", text).strip()
    text = text.strip(" ·")

    if len(text) <= max_chars:
        return text
    # 문장 끝(마침표/물음표/느낌표 뒤 공백)에서 절단 시도
    cut = text[:max_chars]
    for sentinel in [". ", ".\u3000", "? ", "! "]:
        idx = cut.rfind(sentinel)
        if idx > max_chars * 0.6:
            return cut[: idx + 1] + "…"
    return cut.rstrip() + "…"


def _format_chroma_results(raw: dict) -> list[dict]:
    """ChromaDB query() 결과를 부스트 가능한 포맷으로 평탄화."""
    if not raw or not raw.get("ids") or not raw["ids"][0]:
        return []
    results: list[dict] = []
    for i, doc_id in enumerate(raw["ids"][0]):
        distance = raw["distances"][0][i] if raw.get("distances") else 0.0
        similarity = round(1 - distance, 4)
        results.append({
            "id": doc_id,
            "document": raw["documents"][0][i] if raw.get("documents") else "",
            "metadata": raw["metadatas"][0][i] if raw.get("metadatas") else {},
            "score": similarity,
        })
    return results


@lru_cache(maxsize=1)
def _get_reranker() -> "CrossEncoder":
    """Cross-encoder 리랭커 (최초 호출 시 모델 로드, 이후 캐시)."""
    from sentence_transformers import CrossEncoder

    logger.info(f"리랭커 로드 중: {settings.SUBSIDY_RERANKER_MODEL}")
    model = CrossEncoder(settings.SUBSIDY_RERANKER_MODEL, max_length=512)
    return model


# ── 초기 인덱싱 CLI (PDF 업데이트 시 재실행) ─────────────


def run_ingest_pipeline(force_reindex: bool = True) -> int:
    """시행지침 PDF → Markdown → chunk → ChromaDB 인덱싱 파이프라인.

    초기 설치 시 1회, PDF 교체 시마다 재실행:
        uv run python -m app.services.subsidy.gov_rag

    Args:
        force_reindex: True면 기존 컬렉션 삭제 후 재인덱싱 (스키마 변경 시)

    Returns:
        인덱스된 벡터 수
    """
    import asyncio

    from app.services.subsidy.chunker import build_chunks, load_cached_markdown
    from app.services.subsidy.pdf_ingest import parse_subsidy_pdf

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        md = load_cached_markdown()
    except FileNotFoundError:
        md = asyncio.run(parse_subsidy_pdf())

    chunks = build_chunks(md)
    rag = GovSubsidyRAG()
    if force_reindex:
        rag.reset()
    added = rag.index_chunks(chunks)
    logger.info(f"인덱싱 완료: {added}개 벡터 추가 (총 {rag.count()}건)")
    return added


if __name__ == "__main__":
    run_ingest_pipeline()
