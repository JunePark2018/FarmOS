# FarmOS 리뷰 분석 (farmos_review_analysis) — Design Document

> **Feature**: farmos_review_analysis (농산물 리뷰 분석 고도화)
> **Version**: 1.0.0
> **Author**: clover0309
> **Date**: 2026-04-13
> **Status**: Confirmed — **Option C: Pragmatic** 선택됨 (2026-04-13)
> **Plan**: `docs/01-plan/features/farmos_review_analysis.plan.md` v1.1
> **Prior Design**: `docs/archive/2026-04/review-analysis-automation/review-analysis-automation.design.md`

---

## Context Anchor

| Anchor | Content |
|--------|---------|
| **WHY** | Mock 의존성 제거 + 10,000건 더미데이터 기반 실전 검증 + 한국어 임베딩 최적화 |
| **WHO** | 농업인 판매자 (자기 상품 리뷰 분석) + 관리자 (전체 모니터링) |
| **RISK** | 10,000건 임베��� 성능, 한국어 유사도 정확도, ORM 호환성, LLM 비용 |
| **SUCCESS** | Mock 제거, DB 10,000��� 동기���, 임베딩 한국어 검증, 멀티테넌트, 감성분석 80%+ |
| **SCOPE** | Phase 1 (6항목) + Phase 2 (2항목) + Phase 3 (3항목) |

---

## 1. 아키텍처 옵션 비교

### Option A: Minimal — 최소 변경

**원칙**: 기존 코드에 최소한의 수정만 가해서 DB 연동과 Mock 제거를 달성.

**구조**:
- 더미데이터 스크립트는 독립 Python 파일 (`scripts/seed_reviews.py`)
- `api/review_analysis.py`에서 MOCK_REVIEWS 삭제, DB 쿼리를 엔드포인트 내부에 직접 작성
- `review_rag.py`에 `sync_from_db()` 1개 메서드만 추가
- 멀티테넌트는 각 엔드포인트에서 인라인 필터링
- 스케줄러는 `main.py` lifespan에 직접 코드 삽입

```
api/review_analysis.py  ←  DB 쿼�� + 필터링 + 스케줄러 로직 모두 포함
review_rag.py           ←  sync_from_db() 추가
scripts/seed_reviews.py ←  더미데이터 생성 (독립)
```

| 장점 | 단점 |
|------|------|
| 수정 파일 최소 (3~4개) | API 라우터 파일이 비대해짐 (700+ lines) |
| 구현 시간 최단 | 멀티테넌트 로직이 각 엔드포인트에 중복 |
| 학습 곡선 낮음 | 스케줄러와 API가 한 파일에 혼�� |

### Option B: Clean — 완전 분리

**원칙**: 책임을 완전히 분리하여 서비스 레이어를 신규 도입.

**구조**:
- `services/review_service.py` — DB 연동, 멀티테넌트 필터링, 분석 오케스트레이션
- `services/review_data_service.py` — shop_reviews 조회, 데이터 변환
- `core/review_scheduler.py` — APScheduler 독립 모듈
- `scripts/seed_reviews.py` — 더미데이터 생성
- API 라우터��� 서비스 호출만 담당

```
api/review_analysis.py     ←  라우팅만 (thin controller)
services/review_service.py ←  비즈니스 로직 (분석 오케스트레이션)
services/review_data.py    ←  데이터 접근 (shop_reviews 쿼리)
core/review_rag.py         ←  RAG (임베딩/검색만)
core/review_scheduler.py   ←  스케줄러 (독립)
scripts/seed_reviews.py    ←  더미데이터 생성
```

| 장점 | 단점 |
|------|------|
| 완벽한 책임 분리 | 신규 파일 3개 추가 (services 2개 + scheduler) |
| 테스트 용이 | 기존 API 라우터 대폭 리팩토링 필요 |
| 확장성 우수 | 구현 시간 가장 길음 |
| 멀티테넌트 로직 중앙화 | 과도한 추상화 가능성 |

### Option C: Pragmatic — 실용적 균형 (권장)

**원칙**: 기존 "1파일 = 1역할" 패턴을 유지하면서 필요한 부분만 추가. 아카이브의 Option C 패턴 계승.

**구조**:
- `review_rag.py`에 `sync_from_db()` + 멀티테넌트 헬퍼 추가
- `api/review_analysis.py`에서 MOCK_REVIEWS 삭제, DB 연동으로 전환
- `core/review_scheduler.py` — 스케줄러만 분리 (APScheduler 독립성 필요)
- `scripts/seed_reviews.py` — 더미데이터 생성
- 서비스 레이어 도입 없음 — 기존 core 모듈이 서비스 역할 겸임

```
api/review_analysis.py     ←  라우팅 + DB 쿼리 (기존 구조 유지)
core/review_rag.py         ←  RAG + sync_from_db() + 멀티테넌트 필터
core/review_scheduler.py   ←  스케줄��� (신규, 독립)
scripts/seed_reviews.py    ←  더미데이터 생성 (신규)
```

| 장점 | 단점 |
|------|------|
| 기존 1파일=1역할 패턴 유지 | API 라우터가 약간 비대 (~500 lines 유지) |
| 신규 파일 2개만 추가 | 서비스 레이어 없어 복잡한 오케스트레이션은 API에 위치 |
| 아카이브 Option C 패턴 계승 | 멀티테넌트 로직이 rag와 api에 분산 |
| 구현 시간 적절 | |
| 학습 친화적 (파일별 역할 명확) | |

---

## 2. 옵션 비교 테이블

| 평가 기준 | Option A (Minimal) | Option B (Clean) | **Option C (Pragmatic)** |
|-----------|:-:|:-:|:-:|
| **구현 시간** | 1주 | 2~3주 | **1~2주** |
| **신규 파일 수** | 1 (seed) | 4 (seed + service 2 + scheduler) | **2 (seed + scheduler)** |
| **수정 파일 수** | 3 | 5+ (리팩토링) | **4** |
| **기존 구조 유지** | 높음 | 낮음 (리팩토링) | **높음** |
| **코드 가독성** | 중 (비대한 API) | 높음 | **중~높** |
| **테스트 용이성** | 낮음 | 높음 | **중** |
| **확장성** | 낮음 | 높음 | **중** |
| **학습 친화성** | 높음 | 중 (추상화 많음) | **높음** |
| **아카이브 호환** | 부분 | 파괴적 | **완전 호환** |
| **종합 권장** | 단기 데모용 | 대규모 팀 프로젝트 | **현재 프로젝트에 최적** |

---

## 3. 시스템 아키텍처 (Option C 기준)

### 3.1 전체 구조도

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend (React + Vite, port 5173)                         │
│                                                             │
│  ┌──────────────┐  ┌───────────────┐  ┌──────────────────┐ │
│  │ ReviewsPage  │  │ RAGSearchPanel│  │ AnalysisSettings │ │
│  │ (대시���드)    │  │ (의미검색)     │  │ Modal (설정)     │ │
│  └──────┬───────┘  └──────┬────────┘  └────────┬─────────┘ │
│         └────────────┬────┘────────────────────┘           │
│                      ↓                                      │
│              useReviewAnalysis.ts (API 훅)                   │
└─────────────────────┬───────────────────────────────────────┘
                      ↓ HTTP (REST API)
┌─────────────────────┴───────────────────────────────────────┐
│  Backend (FastAPI, port 8000)                                │
│                                                              │
│  ┌────────────────────────────────────────────────────┐     │
│  │  api/review_analysis.py (API Router)                │     │
│  │  - MOCK_REVIEWS 삭제됨                              │     │
│  │  - DB 연동 (asyncpg raw SQL)                        │     │
│  │  - 멀티테넌트 필터링                                 │     │
│  └───���──────────────┬─────────────────────────────────┘     │
│                     ↓                                        │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Core Services (1파일 = 1역할, 기존 유지)              │    │
│  │                                                     │    │
│  │  ┌──────────────────┐   ┌────────────────────┐     │    │
│  │  │  review_rag.py   │   │  review_analyzer.py│     │    │
│  │  │  + sync_from_db()│   │  (기존 유지)        │     │    │
│  │  │  + 멀티테넌트 헬퍼│   │                    │     │    │
│  │  └────────┬─────────┘   └─────────┬──────────┘     │    │
│  │           ↓                       ↓                 │    │
│  │  ┌──────────────┐   ┌──────────────────────┐       │    │
│  │  │  vectordb.py │   │  llm_client_base.py  │       │    │
│  │  │  (기존)       │   │  (기존)               │       │    │
│  │  └──────────────┘   └──────────────────────┘       │    │
│  │                                                     │    │
│  │  ┌──────────────────┐   ┌────────────────────┐     │    │
│  │  │ trend_detector.py│   │  review_report.py  │     │    │
│  │  │  (기존)           │   │  (기존)             │     │    │
│  │  └──────────────────┘   └────────────────────┘     │    │
│  │                                                     │    │
│  │  ┌──────────────────────────────────────────┐      │    │
│  │  │  review_scheduler.py (신규, Phase 2)       │      │    │
│  │  │  APScheduler + AsyncIOScheduler            │      │    │
│  │  └──────────────────────────────────────────┘      │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌──────────────┐   ┌──────────────┐                        │
│  │  PostgreSQL   │   │  ChromaDB    │                        │
│  │  shop_reviews │   │  reviews_    │                        │
│  │  (10,000건)   │   │  llama       │                        │
│  │  review_      │   │  (10,000     │                        │
│  │  analyses     │   │  vectors)    │                        │
│  └──────────────┘   └──────────────┘                        │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  Scripts (독립 실행)                                          │
│  ┌──────────────────────────────────────────┐                │
│  │  scripts/seed_reviews.py (신규, Phase 1)  │                │
│  │  - 더미데이터 10,000건 생성                │                │
│  │  - 긍정 45% / 중립 45% / 부정 10%         │                │
│  └──────────────────────────────────────────┘                │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 데이터 흐름

```
[흐름 0: 더미데이터 생성 — 1회 실행]
scripts/seed_reviews.py
  → psycopg2��� PostgreSQL 직접 INSERT
  → shop_reviews: 기존 30건 + 신규 9,970건 = 10,000건
  → product_id: shop_products 42개 중 랜덤 참조
  → user_id: shop_users 5명 중 랜덤 참조

[흐름 1: DB → ChromaDB 임베딩 (Mock 제거 후)]
POST /api/v1/reviews/embed (source="db")
  → asyncpg: SELECT * FROM shop_reviews WHERE content IS NOT NULL
  → review_rag.sync_from_db(db)
  → OllamaEmbeddingFunction (nomic-embed-text 또는 llama3.1:8b)
  → ChromaDB "reviews_llama" 컬렉션에 10,000 벡터 저장

[흐름 2: 멀티테넌트 RAG 검색]
POST /api/v1/reviews/search (JWT: farmer01)
  → asyncpg: SELECT product_id FROM shop_products WHERE store_id IN (farmer01의 store)
  → review_rag.search(query, where={"product_id": {"$in": [1,5,12]}})
  → ChromaDB 코사인 유사도 검색 (필터 적용)
  → 해당 판매자 상품 리뷰만 반환

[흐름 3: LLM 분석 (기존 유지)]
POST /api/v1/reviews/analyze
  → ChromaDB에서 리뷰 조회
  → ReviewAnalyzer.analyze_batch() — 40건/1호출
  → LLM 1회 호출 = 감성 + 키워드 + 요약 동시

[흐름 4: 자동 배��� (Phase 2)]
APScheduler (매일 22:00)
  → scheduled_analysis()
  → DB에서 신규 리뷰 동기화
  → 자동 분석 실행
  → 결과 DB 저장
```

---

## 4. 모듈별 상세 설계

### 4.1 scripts/seed_reviews.py — 더미데이터 생성 (신규)

```python
"""shop_reviews 더미데이터 10,000건 생성.

실행: python scripts/seed_reviews.py
의존: psycopg2 (shopping_mall과 동일 드라이버)

감성 분포:
  positive (rating 4-5): 45% = 4,500건
  neutral  (rating 3):   45% = 4,500건
  negative (rating 1-2): 10% = 1,000건
"""

# 리뷰 ���플릿 (카테고리별)
POSITIVE_TEMPLATES = [
    "정말 맛있어요! {product}이/가 {adjective}네요.",
    "{product} 품질이 너무 좋아요. 재구매 의사 100%",
    "신선하고 {adjective}! 포장도 깔끔해요.",
    # ... 50+ 템플릿
]

NEUTRAL_TEMPLATES = [
    "{product} 보통��에요. 가격 대비 무난합니다.",
    "기대했던 것보다 평범해요. 그래도 나쁘���는 않아요.",
    # ... 50+ 템플릿
]

NEGATIVE_TEMPLATES = [
    "{product} 포장이 엉망이에요. 배송 중 상했어요.",
    "기대 이하입니다. {adjective} 않아요.",
    # ... 30+ 템플릿
]

def generate_reviews(count: int = 9970) -> list[dict]:
    """감��� 분포에 맞춰 리뷰 생성."""
    ...

def seed_to_db(reviews: list[dict]):
    """psycopg2로 shop_reviews에 INSERT."""
    ...
```

### 4.2 review_rag.py — sync_from_db() 추가

```python
# 기존 ReviewRAG 클래스에 추가

async def sync_from_db(self, db: AsyncSession) -> int:
    """shop_reviews 테이블에서 리뷰를 조회하여 ChromaDB에 동기화.

    Args:
        db: asyncpg 세션

    Returns:
        새로 임베딩된 리뷰 수
    """
    result = await db.execute(
        text("""
            SELECT id, product_id, user_id, rating, content, created_at
            FROM shop_reviews
            WHERE content IS NOT NULL
        """)
    )
    rows = result.fetchall()

    # 이미 임베딩된 ID 제외
    existing_ids = set(self.collection.get()["ids"])
    new_reviews = [
        {
            "id": f"review-{row.id}",
            "text": row.content,
            "rating": row.rating,
            "platform": "",
            "date": row.created_at.strftime("%Y-%m-%d") if row.created_at else "",
            "product_id": row.product_id,
        }
        for row in rows
        if f"review-{row.id}" not in existing_ids
    ]

    if new_reviews:
        return self.embed_reviews(new_reviews)
    return 0

def get_reviews_by_products(self, product_ids: list[int], top_k: int = 100) -> list[dict]:
    """특정 상품 ID의 리뷰만 조회 (멀티테넌트)."""
    results = self.collection.get(
        where={"product_id": {"$in": product_ids}},
        limit=top_k,
    )
    return self._format_results(results)
```

### 4.3 api/review_analysis.py — Mock 제거 + DB 연동

```python
# 변경 사항:
# 1. MOCK_REVIEWS 변수 완전 삭제 (약 500줄 제거)
# 2. embed_reviews 엔드포인트에서 source="db" 기본값
# 3. 멀티테넌트 헬퍼 함수 추가

async def _get_user_product_ids(db: AsyncSession, user_id: str) -> list[int] | None:
    """판매자의 상품 ID 목록 조회. 관리자면 None (전체 접근)."""
    result = await db.execute(
        text("""
            SELECT p.id FROM shop_products p
            JOIN shop_stores s ON p.store_id = s.id
            WHERE s.owner_id = :user_id
        """),
        {"user_id": user_id},
    )
    product_ids = [row.id for row in result.fetchall()]
    return product_ids if product_ids else None  # None = 전체 접근
```

### 4.4 core/review_scheduler.py — APScheduler (신규, Phase 2)

```python
"""리뷰 분석 자동 배치 스케줄러.

APScheduler의 AsyncIOScheduler를 사용하여
FastAPI의 asyncio 이벤트 ���프와 통합.
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler = AsyncIOScheduler()

async def scheduled_analysis():
    """설정된 주기에 맞춰 자동 분석 실행."""
    async with async_session() as db:
        # 1. 신규 리뷰 DB → ChromaDB 동기화
        rag = ReviewRAG()
        synced = await rag.sync_from_db(db)

        if synced > 0:
            # 2. 분석 실행
            analyzer = ReviewAnalyzer()
            reviews = rag.get_all_reviews()
            result = await analyzer.analyze_batch(reviews)

            # 3. 결과 DB 저장
            analysis = ReviewAnalysis(
                analysis_type="batch",
                target_scope="all",
                review_count=len(reviews),
                sentiment_summary=result.get("sentiments_summary"),
                keywords=result.get("keywords"),
                summary=json.dumps(result.get("summary"), ensure_ascii=False),
            )
            db.add(analysis)
            await db.commit()

def start_scheduler():
    """FastAPI lifespan에서 호출."""
    scheduler.add_job(
        scheduled_analysis,
        CronTrigger(hour=22, minute=0),
        id="review_analysis_daily",
        replace_existing=True,
    )
    scheduler.start()

def stop_scheduler():
    """FastAPI shutdown에서 호출."""
    scheduler.shutdown()
```

---

## 5. Session Guide (구현 세션 분할)

### Module Map

```
[Session 1] 더미데이터 + DB 연동
  scripts/seed_reviews.py          (신규, ~150 lines)
  review_rag.py                    (수정, +60 lines)
  api/review_analysis.py           (수정, -500 +50 lines — Mock 삭제)
  schemas/review_analysis.py       (수정, +5 lines)

[Session 2] 임베딩 최적화 + 감성분석 검증
  review_rag.py                    (수정, 모델 벤치마크)
  review_analyzer.py               (수정, 프롬프트 튜닝 — 필요 시)

[Session 3] 멀티테넌트
  api/review_analysis.py           (수정, +80 lines — 필터링 로직)

[Session 4] APScheduler (Phase 2)
  core/review_scheduler.py         (신규, ~100 lines)
  main.py                          (수정, +10 lines)

[Session 5] UX 고도화 (Phase 3)
  ReviewsPage.tsx                  (수정, Mock 폴백 제거)
```

### 세션별 예상 소요 및 산출물

| Session | 소요 | 핵심 산출물 | SC 검증 |
|:-------:|:----:|-----------|---------|
| 1 | 3~4h | 더미 10,000건 + DB 연동 + Mock 삭제 | SC-01, SC-02, SC-03 |
| 2 | 2~3h | 임베딩 검증 결과 + 프롬프트 튜닝 | SC-04, SC-05 |
| 3 | 2h | 멀티테넌트 필터링 | SC-06 |
| 4 | 2h | APScheduler 자동 배치 | SC-07 |
| 5 | 2h | Mock 폴백 제거, UX 완성 | SC-08 |

### 세션 ��존성

```
Session 1 ──→ Session 2 (10,000건 데이터 필요)
Session 1 ──→ Session 3 (DB 연동 필요)
Session 1~3 ──→ Session 4 (Phase 1 완료 후)
Session 1 ──→ Session 5 (DB 연동 완료 후)
```

---

## 6. 리스크 대응 설계

| 리스크 | 설계 대응 |
|--------|----------|
| 10,000건 임베딩 시간 초과 | `embed_reviews_chunked()` 100건씩 분할 + SSE 진행률 (기존 구현 활용) |
| 한국어 임베딩 부정확 | Session 2에서 벤치마크 ��� 모델 전환. fallback: llama3.1:8b |
| shop_stores에 owner_id 없음 | `_get_user_product_ids()`에서 None 반환 시 전체 접근 허용 |
| 감성분석 80% 미달 | Few-shot 예시 추가 → OpenRouter GPT-4o-mini 폴백 |
| 더미데이터 FK 위반 | seed 스크립트에서 실제 product_ids/user_ids 조회 후 참조 |

---

## 7. 아키텍처 선택 결과 (Checkpoint 3 — 완료)

**Option C: Pragmatic** 이 선택되었습니다. (2026-04-13 확정)

| 옵션 | 특징 | 상태 |
|------|------|:----:|
| A: Minimal | 최소 변경, 빠른 구현, API 파일 비대화 | - |
| B: Clean | 완전 분리, 서비스 레이어 도입, 대폭 리팩토링 | - |
| **C: Pragmatic** | **1파일=1역할 유지, 신규 2파일, 아카이브 호환** | **선택됨** |

선택 근거: 기존 아카이브(review-analysis-automation)의 Option C 패턴을 계승하여 학습 친화성과 코드 일관성 유지. 신규 파일 2개만 추가로 최소 비용 구현.
