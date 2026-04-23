"""공익직불 규칙 기반 자격 판정.

사용자 프로필 (User 모델 필드)을 바탕으로 각 지원금 프로그램에 대해
deterministic 자격 판정을 수행합니다. 판정 결과:
    - eligible: 모든 기계적 조건 충족. LLM 재확인 없이도 신청 권장 가능.
    - ineligible: 명확히 결격 (예: 경작 면적 0, 경영체 미등록).
    - needs_review: 사용자 프로필만으로는 완전히 판단 불가. 추가 확인 필요.

설계 원칙:
    - 프로그램별 `check_<code>(profile, subsidy)` 함수를 정의
    - 메인 `match_user(profile, subsidies)` 가 각 프로그램별 체커를 호출
    - **법적 책임 경계**: 확실히 결격인 경우만 "ineligible", 조금이라도 불확실하면 "needs_review"
      → 잘못된 "eligible" 판정은 사용자 피해를 유발할 수 있으나, "needs_review" 는 안내 요청으로 끝나므로 안전

예시:
    async with async_session() as db:
        profile = await build_user_profile(db, user_id="farmer01")
        subsidies = (await db.execute(select(Subsidy))).scalars().all()
        result = match_user(profile, subsidies)
        print(result.eligible, result.needs_review, result.ineligible)
"""

from __future__ import annotations

from app.models.subsidy import Subsidy
from app.schemas.subsidy import EligibilityResult, MatchResponse, UserProfile


# ── 프로그램별 자격 판정 함수 ────────────────────────────────


def check_소농직불금(profile: UserProfile, subsidy: Subsidy) -> EligibilityResult:
    """소농직불금 자격 판정 (2026년 기준, 정액 130만원).

    시행지침 II-3 (청크 CH1_S006) + 공식 농림축산식품부 자료 기반.
    8개 자격요건 중:
        [체크 가능]
        ① 농지 면적: 0.1~0.5ha (표준) 또는 5천㎡ 이상+면적직불금<130만원 (역전구간)
        ② 영농 경력 3년 이상
        ③ 농촌 거주 3년 이상
        ④ 농업경영체 등록 (암묵적 선결 조건)
        [체크 불가 — User 모델에 없음]
        ⑤ 개인 농외소득 < 2,000만원
        ⑥ 농가 구성원 합계 농외소득 < 4,500만원
        ⑦ 농가 구성원 전체 경작면적 < 15.5천㎡ (1.55ha)
        ⑧ 축산업 소득 < 5,600만원
        ⑨ 시설재배 소득 < 3,800만원

    설계 원칙 — 비대칭적 리스크 회피:
        거짓 긍정(실제로는 부적격인데 "eligible" 처리) → 부정수급 처벌 위험 (시행지침 II-8)
        거짓 부정(실제로는 적격인데 "ineligible" 처리) → 사용자가 상담원에게 재확인
        ∴ 불확실하면 항상 "needs_review".
        "ineligible"은 체크 가능한 조건이 명확히 실패한 경우에만.

    역전구간 처리:
        - 경작 면적이 0.5ha 이하: 표준 범위 → needs_review
        - 경작 면적이 0.5~1.55ha: 역전구간 가능성 → needs_review + 안내
        - 경작 면적이 1.55ha 초과: 개인 경작만으로도 농가 제한(15.5천㎡) 초과 → ineligible
    """
    AREA_MIN_HA = 0.1
    AREA_STANDARD_MAX_HA = 0.5
    AREA_REVERSAL_MAX_HA = 1.55   # 15.5천㎡ = 1.55ha — 역전구간 포함 상한
    MIN_YEARS = 3

    # 경영체 등록 — 소농직불은 기본직불의 특수 케이스. 등록이 선결조건.
    if not profile.has_farm_registration:
        return EligibilityResult(
            subsidy_code=subsidy.code,
            subsidy_name=subsidy.name_ko,
            status="ineligible",
            reasons=["농업경영체 등록이 선결 조건입니다. 먼저 농업경영체 등록을 완료하세요."],
            source_articles=subsidy.source_articles,
        )

    # 최소 면적 미달
    if profile.area_ha < AREA_MIN_HA:
        return EligibilityResult(
            subsidy_code=subsidy.code,
            subsidy_name=subsidy.name_ko,
            status="ineligible",
            reasons=[
                f"경작 면적({profile.area_ha}ha)이 최소 기준 0.1ha(1천㎡)에 미달합니다.",
            ],
            source_articles=subsidy.source_articles,
        )

    # 개인 경작 면적만으로도 농가 합계 상한(1.55ha) 초과 — 명확히 불가
    if profile.area_ha > AREA_REVERSAL_MAX_HA:
        return EligibilityResult(
            subsidy_code=subsidy.code,
            subsidy_name=subsidy.name_ko,
            status="ineligible",
            reasons=[
                f"경작 면적({profile.area_ha}ha)이 소농직불 대상 범위(1.55ha, 15.5천㎡)를 초과합니다.",
                "면적직불금 신청을 검토하시기 바랍니다.",
            ],
            source_articles=subsidy.source_articles,
        )

    # 영농 경력 미달
    if profile.years_farming < MIN_YEARS:
        return EligibilityResult(
            subsidy_code=subsidy.code,
            subsidy_name=subsidy.name_ko,
            status="ineligible",
            reasons=[
                f"영농 경력 {MIN_YEARS}년 이상이 필요합니다 (현재 {profile.years_farming}년).",
            ],
            source_articles=subsidy.source_articles,
        )

    # 농촌 거주 연수 미달
    if profile.years_rural_residence < MIN_YEARS:
        return EligibilityResult(
            subsidy_code=subsidy.code,
            subsidy_name=subsidy.name_ko,
            status="ineligible",
            reasons=[
                f"농촌 거주 {MIN_YEARS}년 이상이 필요합니다 (현재 {profile.years_rural_residence}년).",
            ],
            source_articles=subsidy.source_articles,
        )

    # 여기까지 도달 — 체크 가능한 조건은 모두 충족.
    # 남은 소득·농가 단위 조건은 시스템에서 확인 불가하므로 needs_review.
    review_reasons: list[str] = [
        "기본 요건(경영체 등록, 면적, 영농 3년, 거주 3년)은 충족합니다.",
        "다음 항목은 시스템에서 확인할 수 없어 추가 확인이 필요합니다:",
        "• 신청자 개인 농업 외 종합소득 2,000만원 미만",
        "• 농가 구성원 전체 농업 외 종합소득 합계 4,500만원 미만",
        "• 농가 구성원 전체 경작면적 15.5천㎡(1.55ha) 미만",
        "• 축산업 소득 5,600만원 미만",
        "• 시설재배 소득 3,800만원 미만",
        "위 조건까지 모두 충족하시면 연 130만원을 수령하실 수 있습니다.",
    ]

    # 역전구간 안내
    if profile.area_ha > AREA_STANDARD_MAX_HA:
        review_reasons.insert(1, (
            f"[참고] 경작 면적({profile.area_ha}ha)은 표준 범위(0.5ha)를 초과하지만, "
            "'역전구간'(5천㎡ 이상이면서 면적직불금이 130만원 미만)에 해당하는 경우 "
            "여전히 소농직불금 신청이 가능합니다."
        ))

    return EligibilityResult(
        subsidy_code=subsidy.code,
        subsidy_name=subsidy.name_ko,
        status="needs_review",
        reasons=review_reasons,
        estimated_amount_krw=1_300_000,
        source_articles=subsidy.source_articles,
    )


def check_면적직불금(profile: UserProfile, subsidy: Subsidy) -> EligibilityResult:
    """면적직불금 (논/밭) 자격 판정.

    규칙 (시행지침 II-1, II-4 기준):
        - 농업경영체 등록 필수
        - 농지 면적 ≥ 0.1ha (1천㎡)
        - 농지 유형이 subsidy.eligible_farmland_types 에 포함
        - 영농경력 3년 이상
        - 농촌거주 3년 이상 (신규 신청자)
    """
    reasons: list[str] = []
    blocking = False

    # 필수: 농업경영체 등록
    if subsidy.requires_farm_registration and not profile.has_farm_registration:
        reasons.append("농업경영체 등록이 필요합니다.")
        blocking = True

    # 필수: 최소 면적
    if profile.area_ha < subsidy.min_area_ha:
        reasons.append(
            f"경작 면적이 최소 기준({subsidy.min_area_ha}ha) 미만입니다 "
            f"(현재: {profile.area_ha}ha)."
        )
        blocking = True

    # 농지 유형 확인
    eligible_types = subsidy.eligible_farmland_types or []
    if eligible_types and profile.farmland_type and profile.farmland_type not in eligible_types:
        reasons.append(
            f"농지 유형({profile.farmland_type})이 이 지원금 대상이 아닙니다 "
            f"(대상: {', '.join(eligible_types)})."
        )
        blocking = True

    # 영농 경력
    if profile.years_farming < subsidy.min_farming_years:
        reasons.append(
            f"영농 경력이 최소 기준({subsidy.min_farming_years}년) 미만입니다 "
            f"(현재: {profile.years_farming}년)."
        )
        blocking = True

    # 농촌 거주 연수
    if profile.years_rural_residence < subsidy.min_rural_residence_years:
        reasons.append(
            f"농촌 거주 연수가 최소 기준({subsidy.min_rural_residence_years}년) 미만입니다 "
            f"(현재: {profile.years_rural_residence}년)."
        )
        blocking = True

    if blocking:
        return EligibilityResult(
            subsidy_code=subsidy.code,
            subsidy_name=subsidy.name_ko,
            status="ineligible",
            reasons=reasons,
            source_articles=subsidy.source_articles,
        )

    # 예상 지급액 계산
    estimated = _estimate_amount(profile, subsidy)

    return EligibilityResult(
        subsidy_code=subsidy.code,
        subsidy_name=subsidy.name_ko,
        status="eligible",
        reasons=["규칙 기반 자격 요건을 모두 충족합니다. 실제 지급은 경영체 등록·현장 확인 후 확정됩니다."],
        estimated_amount_krw=estimated,
        source_articles=subsidy.source_articles,
    )


# ── 지급액 추정 ────────────────────────────────────────────


def _estimate_amount(profile: UserProfile, subsidy: Subsidy) -> int | None:
    """프로필·payment_structure 기준 예상 수령액 추정.

    구간별 누진 계산: 각 구간의 width = 구간 max - 직전 구간 max (이전 구간 끝점이 현재 구간 시작).
    예: 3ha 논 비진흥 = 2ha×1870000 + 1ha×1790000 = 5,530,000
    """
    ps = subsidy.payment_structure or {}
    if ps.get("type") == "fixed":
        return subsidy.payment_amount_krw

    if ps.get("type") != "tiered_by_area":
        return None

    tiers = ps.get("tiers", [])
    matching_tier = next(
        (t for t in tiers if t.get("promotion_area") == profile.is_promotion_area),
        None,
    )
    if not matching_tier:
        return None

    total = 0
    remaining_ha = profile.area_ha
    prev_top_ha = 0.0
    for rng in matching_tier.get("ranges", []):
        hi = rng.get("max_ha")
        rate = rng.get("amount_per_ha", 0)
        if remaining_ha <= 0:
            break
        tier_top = hi if hi is not None else float("inf")
        width = max(tier_top - prev_top_ha, 0.0)
        applicable_ha = min(remaining_ha, width)
        total += int(applicable_ha * rate)
        remaining_ha -= applicable_ha
        prev_top_ha = tier_top

    return total if total > 0 else None


# ── 메인 라우팅 함수 ────────────────────────────────────────


_CHECKERS = {
    "소농직불금": check_소농직불금,
}


def dispatch_eligibility(profile: UserProfile, subsidy: Subsidy) -> EligibilityResult:
    """지원금 코드로 적절한 체커를 선택하여 판정 결과를 반환.

    Public API — tools.py 및 future deep-agent 가 직접 호출하는 안정 인터페이스.
    """
    checker = _CHECKERS.get(subsidy.code)
    if checker:
        return checker(profile, subsidy)
    # 기본값: 면적직불금 계열은 면적 체커 사용
    if subsidy.code.startswith("면적직불금"):
        return check_면적직불금(profile, subsidy)
    # Fallback — 알 수 없는 프로그램은 needs_review
    return EligibilityResult(
        subsidy_code=subsidy.code,
        subsidy_name=subsidy.name_ko,
        status="needs_review",
        reasons=[f"{subsidy.name_ko}에 대한 자동 판정 로직이 없습니다. 상담을 통해 확인하세요."],
        source_articles=subsidy.source_articles,
    )


def match_user(profile: UserProfile, subsidies: list[Subsidy]) -> MatchResponse:
    """모든 지원금에 대해 자격 판정을 수행하고 결과를 분류한다."""
    eligible: list[EligibilityResult] = []
    ineligible: list[EligibilityResult] = []
    review: list[EligibilityResult] = []

    for sub in subsidies:
        if not sub.is_active:
            continue
        result = dispatch_eligibility(profile, sub)
        if result.status == "eligible":
            eligible.append(result)
        elif result.status == "ineligible":
            ineligible.append(result)
        else:
            review.append(result)

    return MatchResponse(
        user_id=profile.user_id,
        eligible=eligible,
        ineligible=ineligible,
        needs_review=review,
    )
