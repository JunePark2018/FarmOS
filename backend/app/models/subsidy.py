"""공익직불사업 (정부 지원금) 모델.

2026년도 기본형 공익직불사업 시행지침을 구조화하여 저장합니다.
- 소농직불금: 0.1~0.5ha 소규모 농가 정액 지급
- 면적직불금: 농지 유형·진흥지역 여부·면적구간별 단가 차등
- 선택직불금: 친환경·경관보전 등 특정 실천 조건

규칙 기반 사전 필터링에 사용되며, RAG 검색 결과의 인용 근거
(source_articles)를 함께 저장하여 법적 추적성을 보장합니다.
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Subsidy(Base):
    __tablename__ = "subsidies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name_ko: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(40), default="기본형공익직불")
    description: Mapped[str] = mapped_column(Text, default="")

    # 규칙 기반 자격 판정용 구조화 필드
    min_area_ha: Mapped[float] = mapped_column(Float, default=0.0)
    max_area_ha: Mapped[float | None] = mapped_column(Float, nullable=True)
    requires_promotion_area: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    requires_farm_registration: Mapped[bool] = mapped_column(Boolean, default=True)
    min_rural_residence_years: Mapped[int] = mapped_column(Integer, default=0)
    min_farming_years: Mapped[int] = mapped_column(Integer, default=0)

    # 유연한 리스트·테이블 구조는 JSON으로 저장
    eligible_farmland_types: Mapped[list] = mapped_column(JSON, default=list)
    eligible_farmer_types: Mapped[list] = mapped_column(JSON, default=list)
    payment_structure: Mapped[dict] = mapped_column(JSON, default=dict)
    source_articles: Mapped[list] = mapped_column(JSON, default=list)

    # 정액 단가 (소농직불금용). 면적직불금은 payment_structure 사용
    payment_amount_krw: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # UI 노출 순서
    priority: Mapped[int] = mapped_column(Integer, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "code": self.code,
            "name_ko": self.name_ko,
            "category": self.category,
            "description": self.description,
            "min_area_ha": self.min_area_ha,
            "max_area_ha": self.max_area_ha,
            "requires_promotion_area": self.requires_promotion_area,
            "requires_farm_registration": self.requires_farm_registration,
            "min_rural_residence_years": self.min_rural_residence_years,
            "min_farming_years": self.min_farming_years,
            "eligible_farmland_types": self.eligible_farmland_types,
            "eligible_farmer_types": self.eligible_farmer_types,
            "payment_structure": self.payment_structure,
            "source_articles": self.source_articles,
            "payment_amount_krw": self.payment_amount_krw,
            "priority": self.priority,
            "is_active": self.is_active,
        }
