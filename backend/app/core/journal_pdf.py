"""영농일지 PDF 생성 — 농업ON 양식 재현 (Portrait A4, 페이지당 2블록)."""

from datetime import date

from fpdf import FPDF

from app.core.config import settings
from app.models.journal import JournalEntry

# ── 레이아웃 상수 ──

LABEL_W = 30  # 왼쪽 라벨 열 너비
CONTENT_W = 150  # 오른쪽 데이터 열 너비 (A4 세로 210 - 여백 30)
ROW_H = 8  # 기본 행 높이
BLOCK_GAP = 10  # 블록 간 여백
BLOCK_MAX_Y = 270  # 이 Y를 넘으면 새 페이지 (A4 세로 297 - 하단 여백)
CHEM_HALF_W = 75  # 농약/비료 반쪽 너비 (CONTENT_W / 2)
CHEM_COL_W = [20, 30, 25]  # 종류, 제품명, 수량 각 열 너비


class JournalPDF(FPDF):
    """영농일지 전용 PDF (Portrait A4)."""

    def __init__(self, farm_name: str, date_from: date, date_to: date):
        super().__init__(orientation="P", format="A4")
        self.farm_name = farm_name
        self.date_from = date_from
        self.date_to = date_to
        self.add_font("malgun", "", settings.FONT_PATH, uni=True)
        self.add_font("malgun", "B", settings.FONT_PATH, uni=True)
        self.set_auto_page_break(auto=False)
        self.set_margins(15, 15, 15)

    def header(self):
        self.set_font("malgun", "B", 14)
        self.cell(0, 10, "영농일지", align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_font("malgun", "", 9)
        self.cell(
            0,
            6,
            f"농장: {self.farm_name}  |  기간: {self.date_from} ~ {self.date_to}",
            align="C",
            new_x="LMARGIN",
            new_y="NEXT",
        )
        self.ln(4)

    def footer(self):
        self.set_y(-12)
        self.set_font("malgun", "", 7)
        self.cell(0, 10, f"- {self.page_no()} -", align="C")


def _label_cell(pdf: FPDF, text: str, h: float = ROW_H):
    """왼쪽 라벨 셀 (파란 배경)."""
    pdf.set_font("malgun", "B", 8)
    pdf.set_fill_color(230, 240, 250)
    pdf.cell(LABEL_W, h, text, border=1, fill=True, align="C")


def _data_cell(
    pdf: FPDF, text: str, w: float = CONTENT_W, h: float = ROW_H, align: str = "L"
):
    """오른쪽 데이터 셀."""
    pdf.set_font("malgun", "", 8)
    pdf.cell(w, h, f" {text}", border=1, align=align)


def _draw_chem_section(
    pdf: FPDF,
    label: str,
    pest_type: str,
    pest_product: str,
    pest_amount: str,
    fert_type: str,
    fert_product: str,
    fert_amount: str,
    amount_label: str,
):
    """농약/비료 구입 또는 사용 섹션 (라벨 + 헤더행 + 데이터행)."""
    x_start = pdf.get_x()
    y_start = pdf.get_y()

    # 라벨 (3행 병합 = ROW_H * 3)
    section_h = ROW_H * 3
    _label_cell(pdf, label, section_h)

    # 헤더 행 1: "농약" / "비료" 구분
    pdf.set_font("malgun", "B", 7)
    pdf.set_fill_color(245, 248, 245)
    pdf.cell(CHEM_HALF_W, ROW_H, "농약", border=1, fill=True, align="C")
    pdf.cell(CHEM_HALF_W, ROW_H, "비료", border=1, fill=True, align="C")
    pdf.ln()

    # 헤더 행 2: 세부 컬럼명
    pdf.set_x(x_start + LABEL_W)
    pdf.set_font("malgun", "B", 7)
    pdf.set_fill_color(250, 252, 250)
    # 농약 쪽
    for col_name, col_w in zip(["종류", "제품명", amount_label], CHEM_COL_W):
        pdf.cell(col_w, ROW_H, col_name, border=1, fill=True, align="C")
    # 비료 쪽
    for col_name, col_w in zip(["종류", "제품명", amount_label], CHEM_COL_W):
        pdf.cell(col_w, ROW_H, col_name, border=1, fill=True, align="C")
    pdf.ln()

    # 데이터 행
    pdf.set_x(x_start + LABEL_W)
    pdf.set_font("malgun", "", 8)
    # 농약 데이터
    for val, col_w in zip([pest_type, pest_product, pest_amount], CHEM_COL_W):
        pdf.cell(col_w, ROW_H, f" {val}", border=1, align="L")
    # 비료 데이터
    for val, col_w in zip([fert_type, fert_product, fert_amount], CHEM_COL_W):
        pdf.cell(col_w, ROW_H, f" {val}", border=1, align="L")
    pdf.ln()


def _draw_entry_block(pdf: JournalPDF, entry: JournalEntry):
    """일지 1건을 농업ON 양식 블록으로 그리기."""
    x_start = pdf.l_margin

    # 작업일
    pdf.set_x(x_start)
    _label_cell(pdf, "작업일")
    date_str = entry.work_date.strftime("%Y년  %m월  %d일")
    _data_cell(pdf, date_str)
    pdf.ln()

    # 필지
    pdf.set_x(x_start)
    _label_cell(pdf, "필지")
    _data_cell(pdf, entry.field_name)
    pdf.ln()

    # 작목 + 날씨 (같은 행에 2분할)
    pdf.set_x(x_start)
    _label_cell(pdf, "작목")
    half_w = CONTENT_W // 2
    _data_cell(pdf, entry.crop, w=half_w - 15)
    pdf.set_font("malgun", "B", 8)
    pdf.set_fill_color(230, 240, 250)
    pdf.cell(30, ROW_H, "날씨", border=1, fill=True, align="C")
    pdf.set_font("malgun", "", 8)
    pdf.cell(half_w - 15, ROW_H, f" {entry.weather or ''}", border=1)
    pdf.ln()

    # 농약/비료 구입
    pdf.set_x(x_start)
    _draw_chem_section(
        pdf,
        "농약/비료 구입",
        pest_type=entry.purchase_pesticide_type or "",
        pest_product=entry.purchase_pesticide_product or "",
        pest_amount=entry.purchase_pesticide_amount or "",
        fert_type=entry.purchase_fertilizer_type or "",
        fert_product=entry.purchase_fertilizer_product or "",
        fert_amount=entry.purchase_fertilizer_amount or "",
        amount_label="구입량",
    )

    # 농약/비료 사용
    pdf.set_x(x_start)
    _draw_chem_section(
        pdf,
        "농약/비료 사용",
        pest_type=entry.usage_pesticide_type or "",
        pest_product=entry.usage_pesticide_product or "",
        pest_amount=entry.usage_pesticide_amount or "",
        fert_type=entry.usage_fertilizer_type or "",
        fert_product=entry.usage_fertilizer_product or "",
        fert_amount=entry.usage_fertilizer_amount or "",
        amount_label="사용량",
    )

    # 작업단계
    pdf.set_x(x_start)
    _label_cell(pdf, "작업단계")
    _data_cell(pdf, entry.work_stage)
    pdf.ln()

    # 세부작업내용
    pdf.set_x(x_start)
    detail_h = ROW_H * 2
    _label_cell(pdf, "세부작업내용", detail_h)
    pdf.set_font("malgun", "", 8)
    # multi_cell 대신 cell로 높이 고정
    detail_text = (entry.detail or "")[:120]  # 길이 제한
    pdf.cell(CONTENT_W, detail_h, f" {detail_text}", border=1, align="L")
    pdf.ln()


def generate_journal_pdf(
    entries: list[JournalEntry],
    farm_name: str,
    date_from: date,
    date_to: date,
) -> bytes:
    """영농일지 목록을 농업ON 양식 PDF로 생성."""
    pdf = JournalPDF(farm_name, date_from, date_to)
    pdf.add_page()

    sorted_entries = sorted(entries, key=lambda e: (e.work_date, e.id))

    for entry in sorted_entries:
        # 블록이 페이지에 안 들어가면 새 페이지
        if pdf.get_y() > BLOCK_MAX_Y - 100:
            pdf.add_page()
        _draw_entry_block(pdf, entry)
        pdf.ln(BLOCK_GAP)

    if not entries:
        pdf.set_font("malgun", "", 10)
        pdf.ln(20)
        pdf.cell(0, 10, "해당 기간에 기록된 영농일지가 없습니다.", align="C")

    return bytes(pdf.output())
