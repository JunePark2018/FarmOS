"""공익직불 시행지침 Markdown → 구조 인식 청크 분할.

전략:
    1. 본문 시작 페이지 탐지 (CHAPTER 1 타이틀이 단독으로 나타나는 페이지)
    2. CHAPTER 1 / 2 / 3 경계를 본문 내 CHAPTER 마커로 구분
    3. 각 CHAPTER 내부의 Arabic 소단원을 TOC에서 파싱
    4. TOC 항목의 chapter-internal 페이지 → PDF 페이지 offset 계산 (CHAPTER별 독립)
    5. 각 소단원 범위를 슬라이스하여 청크 생성
    6. 별표는 별도 스캔으로 추가

청크 크기 안전장치:
    - 5KB 미만: 그대로
    - 5~15KB: 그대로 (장문 법조문 허용)
    - 15KB 초과: 페이지 단위로 분할 (별표, 긴 세목의 경우)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)


# ── 플레이스홀더 라벨 (청크 메타데이터의 section 필드) ──────────
# 이 상수들은 gov_rag 의 Citation 빌더에서도 동일하게 참조되므로
# 문자열 변경 시 반드시 여기서만 수정할 것.
PLACEHOLDER_NO_PARENT_SECTION = "(장 내 최상위 절)"   # Roman-leaf 챕터: 상위 절 개념 없음
PLACEHOLDER_PARENT_UNKNOWN = "(상위 미지정)"            # Arabic 항목인데 선행 Roman 이 없는 경우

PLACEHOLDER_SECTION_LABELS: frozenset[str] = frozenset({
    PLACEHOLDER_NO_PARENT_SECTION,
    PLACEHOLDER_PARENT_UNKNOWN,
})


# ── 노이즈 제거 ─────────────────────────────────────────────

NOISE_PATTERNS: list[tuple[str, str]] = [
    (r"!\[image\]\([^)]+\)", ""),
    (r"기본형 공익직불사업 시행지침\s*\|\s*\d+\b", ""),
    (r"\d+\s*\|\s*2026년도 기본형 공익직불사업 시행지침서", ""),
    (r"www\.mafra\.go\.kr", ""),
    (r"\\\s+", " "),
    (r"[ \t]+", " "),
]


def strip_noise(text: str) -> str:
    for pat, repl in NOISE_PATTERNS:
        text = re.sub(pat, repl, text)
    return text


# ── 페이지 분할 ─────────────────────────────────────────────

PAGE_MARKER_RE = re.compile(r"<!-- page:(\d+) -->")


@dataclass
class Page:
    number: int
    content: str


def split_by_pages(markdown: str) -> list[Page]:
    pages: list[Page] = []
    parts = PAGE_MARKER_RE.split(markdown)
    for i in range(1, len(parts), 2):
        page_num = int(parts[i])
        content = parts[i + 1] if i + 1 < len(parts) else ""
        pages.append(Page(number=page_num, content=content.strip()))
    return pages


# ── 본문 시작·챕터 경계 탐지 (TOC 혼동 방지) ─────────────────

CHAPTER_BODY_TITLE_RE = re.compile(
    r"CHAPTER\s+(\d+)\s*\n?\s*(?:기본형|공익직불|관련)"
)


def find_chapter_boundaries(pages: list[Page]) -> dict[int, int]:
    """각 CHAPTER가 시작하는 PDF 페이지 번호를 반환.

    CHAPTER 타이틀 페이지는 보통 "CHAPTER N 기본형 공익직불..." 같이 단독 출현.
    TOC 항목 ("CHAPTER N. ... 페이지번호")과는 구조가 다름.
    """
    boundaries: dict[int, int] = {}
    for page in pages:
        m = CHAPTER_BODY_TITLE_RE.search(page.content)
        if m:
            chapter_num = int(m.group(1))
            if chapter_num not in boundaries:
                boundaries[chapter_num] = page.number
    return boundaries


# ── TOC 파싱 ────────────────────────────────────────────────

# TOC 항목: "3. 소농직불 지급대상 자격요건 20"  또는  "II. 농약... 140"
# Upstage가 Roman I를 파이프(|)로 오인하는 경우가 있어 '|' 도 허용.
TOC_ITEM_RE = re.compile(
    r"(?:^|\n)\s*[-·▽☑]?\s*"
    r"(?P<num>[IVX]+|\d{1,2}|\|)\.?\s+"
    r"(?P<title>[^\n0-9|]{2,80}?)\s+"
    r"(?P<page>\d{1,3})\s*(?=\n|$)"
)


@dataclass
class TocEntry:
    chapter_num: int         # 1, 2, 3
    level: str               # "roman" | "arabic"
    number: str              # "II" / "3"
    title: str
    page: int                # chapter-internal page (TOC에 적힌 숫자)


def parse_toc(pages: list[Page], ch_starts: dict[int, int]) -> list[TocEntry]:
    """각 챕터 본문 시작 전 페이지를 TOC로 간주하고 항목을 수집.

    처음 TOC는 CHAPTER 1 시작 직전까지.
    """
    ch1_start = ch_starts.get(1)
    if ch1_start is None:
        logger.warning("CHAPTER 1 본문 시작을 찾지 못해 TOC 파싱 실패")
        return []

    toc_pages = [p for p in pages if p.number < ch1_start]
    toc_text = "\n".join(p.content for p in toc_pages)

    # TOC 내 CHAPTER 마커 위치로 chapter_num 추적
    ch_marker_re = re.compile(r"CHAPTER\s+(\d+)\.")
    ch_positions = [(m.start(), int(m.group(1))) for m in ch_marker_re.finditer(toc_text)]

    def chapter_at(offset: int) -> int:
        num = 1
        for pos, n in ch_positions:
            if pos <= offset:
                num = n
            else:
                break
        return num

    entries: list[TocEntry] = []
    for m in TOC_ITEM_RE.finditer(toc_text):
        num_raw = m.group("num").strip()
        # '|' 파이프 오인식 보정 → Roman "I" 로 복원
        num = "I" if num_raw == "|" else num_raw
        title = m.group("title").strip(" ·-|")
        page = int(m.group("page"))
        if page < 3 or page > 400:
            continue
        level = "roman" if re.match(r"^[IVX]+$", num) else "arabic"
        entries.append(TocEntry(
            chapter_num=chapter_at(m.start()),
            level=level,
            number=num,
            title=title,
            page=page,
        ))

    # 본문 스캔 fallback: Roman-leaf 챕터에 'I' 가 누락된 경우 (Upstage 'I'→'|' 오인식)
    entries = _augment_missing_roman_I(entries, pages, ch_starts)
    return entries


def _augment_missing_roman_I(
    toc: list[TocEntry],
    pages: list[Page],
    ch_starts: dict[int, int],
) -> list[TocEntry]:
    """Roman-leaf 챕터에 'I' 가 없으면 본문에서 찾아 합성 엔트리를 추가.

    배경:
        Upstage Document Parse가 Roman 숫자 'I' 를 파이프 '|' 로 잘못 인식하는
        경우가 있음. 특히 CHAPTER 2 같이 한 줄에 챕터 타이틀과 첫 절이 함께
        출력되면 TOC 정규식이 Section I 을 놓침.

    접근:
        1) 해당 챕터의 첫 Roman 엔트리 (예: II) 의 제목 anchor 를 본문에서 찾아 offset 계산
        2) Chapter 시작~첫 알려진 Roman PDF 페이지 사이 에서 "I <한글 제목>" 패턴 스캔
        3) 찾으면 합성 TocEntry (level="roman", number="I") 추가
    """
    result = list(toc)
    pages_by_num = {p.number: p for p in pages}

    for ch_num, ch_start in ch_starts.items():
        ch_entries = [e for e in result if e.chapter_num == ch_num]
        if any(e.level == "arabic" for e in ch_entries):
            continue   # arabic-leaf chapter (e.g. CHAPTER 1) — 건너뜀

        romans = sorted(
            (e for e in ch_entries if e.level == "roman"),
            key=lambda e: e.page,
        )
        if not romans or romans[0].number == "I":
            continue   # 이미 I 가 있음

        # 첫 알려진 Roman 의 제목 첫 단어로 PDF 위치 파악 (offset 계산용)
        first = romans[0]
        anchor = first.title.split()[0] if first.title else ""
        if not anchor:
            continue
        first_pdf_page: int | None = None
        for p_num in sorted(pages_by_num):
            if p_num < ch_start:
                continue
            if anchor in pages_by_num[p_num].content[:500]:
                first_pdf_page = p_num
                break
        if first_pdf_page is None:
            continue
        offset = first_pdf_page - first.page

        # Chapter 시작과 첫 알려진 Roman PDF 사이를 스캔.
        # CH2 페이지 구조: "이행점검 지침 I {TITLE} 이 지침은..." — 줄 중간에 Roman이 들어옴.
        # 따라서 line-start 대신 "지침" 앵커와 "이 지침은" 종결부로 경계를 잡는다.
        patterns = [
            # 인라인: "...지침 I 제목 이 지침은..." (CH2 관찰 포맷)
            re.compile(
                r"지침\s+I\s+(?P<title>[가-힣][가-힣\s·및]{3,50}?)\s+이\s*지침은"
            ),
            # 헤더형: "# I 제목" 또는 line start "I 제목" (백업)
            re.compile(
                r"(?:^|\n)\s*(?:#\s*)?I\b\s*\.?\s*(?P<title>[가-힣][가-힣\s·및]{3,50})"
            ),
        ]
        for p_num in range(ch_start, first_pdf_page):
            page = pages_by_num.get(p_num)
            if not page:
                continue
            found = False
            for pat in patterns:
                m = pat.search(page.content[:800])
                if m:
                    title = m.group("title").strip().rstrip(" ·-")
                    synth_toc_page = p_num - offset
                    result.append(TocEntry(
                        chapter_num=ch_num,
                        level="roman",
                        number="I",
                        title=title,
                        page=synth_toc_page,
                    ))
                    logger.info(
                        f"본문 스캔으로 CH{ch_num} Section I 보강: '{title}' (PDF p{p_num})"
                    )
                    found = True
                    break
            if found:
                break

    result.sort(key=lambda e: (e.chapter_num, e.page))
    return result


# ── 별표 탐지 ────────────────────────────────────────────────
# 핵심 제약:
#   (1) 별표 N이 페이지 최상단 근처 (처음 100자 이내)에서 등장해야 함
#       → 본문 중간의 "별표 N에 따라..." 같은 인라인 참조 배제
#   (2) 번호가 단조 증가해야 함 (별표 1, 2, 3 ... 순서)
#       → 뒤로 가면서 작은 번호가 나오면 인라인 가능성이 높음
#   (3) 별표 N 뒤에는 구두점 또는 공백 + 줄바꿈만 허용
#       → "별표 4 카목)" 같은 legal citation 제거

BYEOLPYO_HEAD_RE = re.compile(
    r"^\s*[\[\(<『]?\s*(?:#\s*)?별표\s*(\d{1,2})\s*[\]\)>』]?\s*(?:\n|$)"
)
# 별표 제목 (별표 번호 바로 다음 줄의 한글 제목)
BYEOLPYO_TITLE_RE = re.compile(r"\n\s*([가-힣][^\n]{2,60})")


def find_byeolpyo_pages(pages: list[Page], ch_starts: dict[int, int]) -> list[dict]:
    """별표 N이 '페이지 상단 단독 헤더'로 등장하는 경우만 탐지.

    인라인 참조("별표 4 카목)...")는 제외. 번호 단조 증가 규칙 적용.
    """
    results: list[dict] = []
    last_num = 0

    for page in pages:
        if not page.content:
            continue
        # 페이지 앞쪽 150자만 검사 (헤더 영역)
        head = page.content[:150].lstrip()
        m = BYEOLPYO_HEAD_RE.match(head)
        if not m:
            continue
        num = int(m.group(1))
        if num < last_num:
            # 번호가 감소 — 인라인일 가능성 높음
            logger.debug(f"별표 {num} at page {page.number}: 번호 감소로 배제")
            continue
        last_num = num

        # 제목: 별표 번호 뒤 첫 줄
        tail = page.content[m.end():][:200]
        title_m = BYEOLPYO_TITLE_RE.search("\n" + tail)
        title = title_m.group(1).strip() if title_m else ""

        results.append({
            "number": str(num),
            "title": title,
            "page_start": page.number,
        })

    # page_end 채움 (다음 별표 시작 - 1, 마지막은 문서 끝)
    for i in range(len(results) - 1):
        results[i]["page_end"] = results[i + 1]["page_start"] - 1
    if results:
        results[-1]["page_end"] = max(p.number for p in pages)
    return results


# ── 청크 구성 ───────────────────────────────────────────────

@dataclass
class Chunk:
    id: str
    content: str
    chapter: str
    section: str
    subsection: str
    subsection_title: str
    page_start: int
    page_end: int
    section_type: str = "본문"           # 본문 | 별표

    def char_len(self) -> int:
        return len(self.content)


MAX_CHUNK_CHARS = 15_000   # 초과 시 페이지 단위로 분할


def _offset_for_chapter(
    pages: list[Page], toc: list[TocEntry], chapter_num: int, chapter_start_page: int
) -> int:
    """주어진 챕터의 chapter-internal → PDF page offset 계산.

    해당 챕터의 첫 TOC 항목(arabic 우선, 없으면 roman)의 제목 키워드가
    챕터 본문에서 나타나는 페이지를 기준으로 계산.
    """
    ch_entries = [e for e in toc if e.chapter_num == chapter_num]
    if not ch_entries:
        return 0
    # arabic 우선, 없으면 roman 사용
    first = next(
        (e for e in ch_entries if e.level == "arabic"),
        ch_entries[0],
    )
    anchor = first.title.split()[0] if first.title else ""
    if not anchor:
        return 0

    pattern = re.compile(rf"\b{re.escape(anchor)}\b")
    for page in pages:
        if page.number < chapter_start_page:
            continue
        if pattern.search(page.content):
            return page.number - first.page
    return chapter_start_page - first.page + 2


def build_chunks(markdown: str) -> list[Chunk]:
    cleaned = strip_noise(markdown)
    pages = split_by_pages(cleaned)
    if not pages:
        return []

    pages_by_num = {p.number: p for p in pages}
    ch_starts = find_chapter_boundaries(pages)
    logger.info(f"CHAPTER 시작 페이지: {ch_starts}")

    toc = parse_toc(pages, ch_starts)
    logger.info(f"TOC 항목: {len(toc)}개 (chapter별: "
                f"1={sum(1 for e in toc if e.chapter_num==1)}, "
                f"2={sum(1 for e in toc if e.chapter_num==2)}, "
                f"3={sum(1 for e in toc if e.chapter_num==3)})")

    # 챕터별 offset
    offsets: dict[int, int] = {}
    for ch_num, ch_start in ch_starts.items():
        offsets[ch_num] = _offset_for_chapter(pages, toc, ch_num, ch_start)
    logger.info(f"챕터별 offset: {offsets}")

    chunks: list[Chunk] = []

    # 챕터별로 독립 처리
    for ch_num in sorted(ch_starts.keys()):
        ch_start = ch_starts[ch_num]
        next_ch_start = min(
            (s for c, s in ch_starts.items() if c > ch_num),
            default=max(p.number for p in pages) + 1,
        )
        offset = offsets.get(ch_num, 0)

        # 이 챕터의 TOC 항목 (상위→하위 순)
        ch_toc = [e for e in toc if e.chapter_num == ch_num]
        if not ch_toc:
            continue

        # 챕터별 leaf 레벨 결정: arabic이 있으면 arabic, 없으면 roman이 leaf
        has_arabic = any(e.level == "arabic" for e in ch_toc)
        leaf_level = "arabic" if has_arabic else "roman"

        # leaf 항목 + 상위 section 메타데이터 구성
        leaves_with_section: list[tuple[TocEntry, str]] = []
        current_section = ""
        for e in ch_toc:
            if leaf_level == "arabic":
                if e.level == "roman":
                    current_section = f"{e.number}. {e.title}"
                else:
                    leaves_with_section.append((e, current_section or PLACEHOLDER_PARENT_UNKNOWN))
            else:
                # leaf == roman: roman 자체가 leaf이고 상위 section 개념 없음
                if e.level == "roman":
                    leaves_with_section.append((e, PLACEHOLDER_NO_PARENT_SECTION))

        # 각 leaf 항목 → 청크
        arabic_with_section = leaves_with_section   # 기존 변수명 유지
        for i, (entry, section) in enumerate(arabic_with_section):
            pdf_start = entry.page + offset
            # 다음 arabic의 시작 페이지까지. 없으면 다음 챕터 시작 - 1.
            if i + 1 < len(arabic_with_section):
                next_arabic = arabic_with_section[i + 1][0]
                pdf_end = next_arabic.page + offset - 1
            else:
                pdf_end = next_ch_start - 1

            # 챕터 경계 초과 방지
            pdf_start = max(pdf_start, ch_start)
            pdf_end = min(pdf_end, next_ch_start - 1)
            if pdf_start > pdf_end:
                continue

            content_parts = []
            for pn in range(pdf_start, pdf_end + 1):
                page = pages_by_num.get(pn)
                if page and page.content:
                    content_parts.append(page.content)
            content = "\n\n".join(content_parts).strip()
            if not content or len(content) < 100:
                continue

            chapter_label = f"CHAPTER {ch_num}"
            base_id = f"CH{ch_num}_S{i:03d}"

            # 너무 크면 페이지 단위 분할
            if len(content) > MAX_CHUNK_CHARS:
                for j, pn in enumerate(range(pdf_start, pdf_end + 1)):
                    page = pages_by_num.get(pn)
                    if not page or not page.content:
                        continue
                    sub_content = page.content.strip()
                    if len(sub_content) < 100:
                        continue
                    chunks.append(Chunk(
                        id=f"{base_id}_p{pn}",
                        content=sub_content,
                        chapter=chapter_label,
                        section=section,
                        subsection=f"{entry.number}. {entry.title}",
                        subsection_title=entry.title,
                        page_start=pn,
                        page_end=pn,
                        section_type="본문",
                    ))
            else:
                chunks.append(Chunk(
                    id=base_id,
                    content=content,
                    chapter=chapter_label,
                    section=section,
                    subsection=f"{entry.number}. {entry.title}",
                    subsection_title=entry.title,
                    page_start=pdf_start,
                    page_end=pdf_end,
                    section_type="본문",
                ))

    # 별표 청크 추가
    for bp in find_byeolpyo_pages(pages, ch_starts):
        start = bp["page_start"]
        end = bp["page_end"]
        parts = []
        for pn in range(start, end + 1):
            page = pages_by_num.get(pn)
            if page and page.content:
                parts.append(page.content)
        content = "\n\n".join(parts).strip()
        if not content or len(content) < 100:
            continue

        if len(content) > MAX_CHUNK_CHARS:
            for pn in range(start, end + 1):
                page = pages_by_num.get(pn)
                if not page or len(page.content) < 100:
                    continue
                chunks.append(Chunk(
                    id=f"BP{bp['number']}_p{pn}",
                    content=page.content.strip(),
                    chapter="별표",
                    section=f"별표 {bp['number']}",
                    subsection=f"별표 {bp['number']} {bp['title']}".strip(),
                    subsection_title=bp["title"],
                    page_start=pn,
                    page_end=pn,
                    section_type="별표",
                ))
        else:
            chunks.append(Chunk(
                id=f"BP{bp['number']}",
                content=content,
                chapter="별표",
                section=f"별표 {bp['number']}",
                subsection=f"별표 {bp['number']} {bp['title']}".strip(),
                subsection_title=bp["title"],
                page_start=start,
                page_end=end,
                section_type="별표",
            ))

    return chunks


# ── 유틸 ────────────────────────────────────────────────────

def load_cached_markdown() -> str:
    """pdf_ingest 가 저장한 Markdown 캐시를 로드 (인덱싱용)."""
    base = Path(__file__).resolve().parents[3]
    md_path = base / settings.SUBSIDY_MARKDOWN_CACHE_PATH
    if not md_path.exists():
        raise FileNotFoundError(f"Markdown 캐시가 없습니다: {md_path}")
    return md_path.read_text(encoding="utf-8")
