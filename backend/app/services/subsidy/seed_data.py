"""공익직불 기본형 3개 프로그램 시드 데이터 (2026년 확정값).

출처: 2026년도 기본형 공익직불사업 시행지침 (파싱 검증 완료)
    - 소농직불금: II-3 (정액 130만원, 2025 대비 +10만원)
    - 면적직불금: II-4 (3단계 역진적 단가, 2026 단가 적용)

2026 지급단가 (만원/ha, 시행지침 II-4 표 기준):
    | 구분              | 2ha 이하 | 2~6ha | 6ha 초과 |
    | 논 진흥지역       | 215      | 207   | 198      |
    | 논 비진흥 = 밭 진흥| 187     | 179   | 170      |
    | 밭 비진흥지역     | 150      | 143   | 136      |

    ※ 시행지침 예시: 논 진흥 4ha + 논 비진흥 3ha + 밭 비진흥 2ha = 총 1,644만원
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subsidy import Subsidy


SEED_SUBSIDIES: list[dict] = [
    {
        "code": "소농직불금",
        "name_ko": "소농직불금",
        "category": "기본형공익직불",
        "description": (
            "소규모 농가(경작 0.1~0.5ha, 역전구간 포함 시 최대 1.55ha)에 "
            "연 130만원 정액 지급. 농업경영체 등록·농촌 3년 거주·영농 3년 경력 외에 "
            "농외소득·농가소득합계·축산소득·시설재배소득 기준을 모두 충족해야 함."
        ),
        "min_area_ha": 0.1,
        "max_area_ha": 1.55,     # 역전구간 포함 상한
        "requires_promotion_area": None,
        "requires_farm_registration": True,
        "min_rural_residence_years": 3,
        "min_farming_years": 3,
        "eligible_farmland_types": ["논", "밭", "과수", "시설"],
        "eligible_farmer_types": ["일반", "청년", "후계", "귀농"],
        "payment_structure": {
            "type": "fixed",
            "amount_krw": 1_300_000,
            "income_conditions": {
                "개인_농외소득_상한만원": 2000,
                "가구합계_농외소득_상한만원": 4500,
                "축산소득_상한만원": 5600,
                "시설재배소득_상한만원": 3800,
                "농가_경작면적_상한제곱미터": 15500,
            },
            "note": "시스템에서 확인 불가 — 신청 시 별도 검증",
        },
        "payment_amount_krw": 1_300_000,
        "source_articles": ["CHAPTER 1 II-3 소농직불 지급대상 자격요건"],
        "priority": 10,
    },
    {
        "code": "면적직불금_논농업",
        "name_ko": "면적직불금 (논농업)",
        "category": "기본형공익직불",
        "description": (
            "논농업 경작 농지에 면적구간별 단가 차등 지급. "
            "진흥지역(215/207/198만원/ha) · 비진흥지역(187/179/170만원/ha) 구분. "
            "구간: 2ha 이하 / 2~6ha / 6ha 초과 (역진적 단가 적용)."
        ),
        "min_area_ha": 0.1,
        "max_area_ha": 30.0,    # 개인 농업인 지급 상한 (시행지침 II-4 지급상한)
        "requires_promotion_area": None,
        "requires_farm_registration": True,
        "min_rural_residence_years": 3,
        "min_farming_years": 3,
        "eligible_farmland_types": ["논"],
        "eligible_farmer_types": ["일반", "청년", "후계", "귀농"],
        "payment_structure": {
            "type": "tiered_by_area",
            "tiers": [
                {
                    "promotion_area": True,
                    "label": "논 진흥지역",
                    "ranges": [
                        {"min_ha": 0.1, "max_ha": 2.0, "amount_per_ha": 2_150_000},
                        {"min_ha": 2.0, "max_ha": 6.0, "amount_per_ha": 2_070_000},
                        {"min_ha": 6.0, "max_ha": 30.0, "amount_per_ha": 1_980_000},
                    ],
                },
                {
                    "promotion_area": False,
                    "label": "논 비진흥지역",
                    "ranges": [
                        {"min_ha": 0.1, "max_ha": 2.0, "amount_per_ha": 1_870_000},
                        {"min_ha": 2.0, "max_ha": 6.0, "amount_per_ha": 1_790_000},
                        {"min_ha": 6.0, "max_ha": 30.0, "amount_per_ha": 1_700_000},
                    ],
                },
            ],
            "note": "시행지침 II-4, 2026년 확정 단가",
        },
        "payment_amount_krw": None,
        "source_articles": ["CHAPTER 1 II-4 지급단가"],
        "priority": 20,
    },
    {
        "code": "면적직불금_밭농업",
        "name_ko": "면적직불금 (밭농업)",
        "category": "기본형공익직불",
        "description": (
            "밭농업 경작 농지에 면적구간별 단가 차등 지급. "
            "진흥지역(187/179/170만원/ha) · 비진흥지역(150/143/136만원/ha) 구분. "
            "구간: 2ha 이하 / 2~6ha / 6ha 초과 (역진적 단가 적용). "
            "※ 밭 진흥지역 = 논 비진흥지역과 동일 단가 (2026년 기준)."
        ),
        "min_area_ha": 0.1,
        "max_area_ha": 30.0,
        "requires_promotion_area": None,
        "requires_farm_registration": True,
        "min_rural_residence_years": 3,
        "min_farming_years": 3,
        "eligible_farmland_types": ["밭", "과수", "시설"],
        "eligible_farmer_types": ["일반", "청년", "후계", "귀농"],
        "payment_structure": {
            "type": "tiered_by_area",
            "tiers": [
                {
                    "promotion_area": True,
                    "label": "밭 진흥지역",
                    "ranges": [
                        {"min_ha": 0.1, "max_ha": 2.0, "amount_per_ha": 1_870_000},
                        {"min_ha": 2.0, "max_ha": 6.0, "amount_per_ha": 1_790_000},
                        {"min_ha": 6.0, "max_ha": 30.0, "amount_per_ha": 1_700_000},
                    ],
                },
                {
                    "promotion_area": False,
                    "label": "밭 비진흥지역",
                    "ranges": [
                        {"min_ha": 0.1, "max_ha": 2.0, "amount_per_ha": 1_500_000},
                        {"min_ha": 2.0, "max_ha": 6.0, "amount_per_ha": 1_430_000},
                        {"min_ha": 6.0, "max_ha": 30.0, "amount_per_ha": 1_360_000},
                    ],
                },
            ],
            "note": "시행지침 II-4, 2026년 확정 단가",
        },
        "payment_amount_krw": None,
        "source_articles": ["CHAPTER 1 II-4 지급단가"],
        "priority": 30,
    },
]


async def seed_subsidies(db: AsyncSession) -> int:
    """지원금 시드 데이터를 upsert (신규 삽입 또는 기존 행 필드 갱신).

    시행지침 단가·자격요건이 수정되면 SEED_SUBSIDIES 만 수정 후 재기동하면
    반영된다. SQLAlchemy 의 dirty 추적이 실제 값이 다른 컬럼만 UPDATE 를
    발급하므로, 값이 동일한 재기동에서는 DB write 가 거의 발생하지 않는다.
    (JSON 컬럼은 dict 비교가 보수적으로 동작해 매 기동 1회 UPDATE 가 날 수
    있으나 3개 행 규모에서 허용 가능).

    Returns:
        신규 삽입 + 갱신된 행 수 (로깅용)
    """
    changed = 0
    for data in SEED_SUBSIDIES:
        result = await db.execute(
            select(Subsidy).where(Subsidy.code == data["code"])
        )
        row = result.scalar_one_or_none()
        if row is None:
            db.add(Subsidy(**data))
            changed += 1
            continue
        # 기존 행은 모든 시드 필드를 덮어쓴다 (code 는 PK·불변이므로 스킵)
        for field, value in data.items():
            if field == "code":
                continue
            if getattr(row, field, None) != value:
                setattr(row, field, value)
    # dirty 가 있으면 SQLAlchemy 가 자동 UPDATE 발급
    await db.commit()
    return changed
