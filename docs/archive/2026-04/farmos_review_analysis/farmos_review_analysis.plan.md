# FarmOS 리뷰 분석 (farmos_review_analysis) — Plan Document

> **Feature**: farmos_review_analysis (농산물 리뷰 분석 고도화)
> **Version**: 1.1.0
> **Author**: clover0309
> **Date**: 2026-04-13
> **Status**: Draft (v1.1 — 요구사항 수정 반영)
> **PRD**: `docs/00-pm/farmos_review_analysis.prd.md`
> **Prior Work**: `docs/archive/2026-04/review-analysis-automation/` (96% match rate)

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 리뷰 분석 시스템이 Mock 500건 하드코딩 데이터에 의존하며, 실제 DB(shop_reviews 30건) 연동 없음. 대규모 데이터 테스트 불가, 자동 배치 스케줄러 미구현, 판매자별 리뷰 필터링 불가, 임베딩 한국어 검증 미완, 프론트엔드에 Mock 폴백 로직 혼재 |
| **Solution** | Mock 데이터 완전 제거 + 더미데이터 10,000건 생성 + DB 연동 + 한국어 임베딩 최적화 + 멀티테넌트 + 감성분석 검증을 Phase 1에서 일괄 해결. Phase 2에서 APScheduler 자동화, Phase 3에서 UX 고도화 |
| **Function/UX Effect** | 판매자가 자기 상품 리뷰 인사이트를 실시간 대시보드로 확인. 10,000건 규모의 현실적 데이터로 분석 품질 검증. 신규 리뷰 자동 분석 |
| **Core Value** | 기존 96% 구현을 100% 운영 가능 상태로 전환. 대규모 더미데이터로 실전 검증 + Mock 의존성 완전 제거 |

---

## Context Anchor

| Anchor | Content |
|--------|---------|
| **WHY** | Mock 의존성을 제거하고 10,000건 규모의 현실적 데이터로 분석 파이프라인을 실전 검증하여, 농산물 판매자가 리뷰 인사이트를 데이터 기반으로 활용할 수 있게 함 |
| **WHO** | 농업인 판매자 (자기 상품 리뷰 분석) + 관리자 (전체 모니터링 + PDF 리포트) |
| **RISK** | shop_reviews↔shopping_mall ORM 호환성, 10,000건 임베딩 성능, 한국어 임베딩 정확도, LLM 비용 |
| **SUCCESS** | Mock 완전 제거, 더미 10,000건 DB 투입, 임베딩 한국어 검증 완료, 판매자별 필터링 동작, 감성분석 80%+ |
| **SCOPE** | Mock 제거 + 더미데이터 생성 + DB 연동 + 임베딩 최적화 + 멀티테넌트 + 감성분석 검증 + 스케줄러 + UX 고도화 (8개 항목) |

---

## 1. 현재 상태 분석

### 1.1 코드베이스 현황

#### 백엔드 (구현 완료, 수정 필요)

| 파일 | 상태 | 수정 필요 사항 |
|------|:----:|--------------|
| `backend/app/core/llm_client_base.py` (~230 lines) | 완료 | 변경 없음 |
| `backend/app/core/review_rag.py` (~220 lines) | 완료 | DB 리뷰 동기화 메서드 추가 |
| `backend/app/core/review_analyzer.py` (~220 lines) | 완료 | 정확도 검증 후 프롬프트 튜닝 |
| `backend/app/core/trend_detector.py` (~200 lines) | 완료 | 변경 없음 |
| `backend/app/core/review_report.py` (~200 lines) | 완료 | 변경 없음 |
| `backend/app/models/review_analysis.py` (~45 lines) | 완료 | 변경 없음 |
| `backend/app/schemas/review_analysis.py` (~165 lines) | 완료 | EmbedRequest에 source="db" 기본값 변경 |
| `backend/app/api/review_analysis.py` (~540 lines) | 완료 | MOCK_REVIEWS 삭제 + DB 연동 + 멀티테넌트 필터링 |

#### 프론트엔드 (구현 완료, UX 고도화 필요)

| 파일 | 상태 | 수정 필요 사항 |
|------|:----:|--------------|
| `frontend/src/hooks/useReviewAnalysis.ts` (~160 lines) | 완료 | 변경 없음 |
| `frontend/src/modules/reviews/RAGSearchPanel.tsx` (~115 lines) | 완료 | 변경 없음 |
| `frontend/src/modules/reviews/AnalysisSettingsModal.tsx` (~115 lines) | 완료 | 변경 없음 |
| `frontend/src/modules/reviews/ReviewsPage.tsx` (~200 lines) | 완료 | Mock 폴백 제거, 빈 상태/에러 UX |
| `frontend/src/mocks/reviews.ts` | Mock 데이터 | Phase 3에서 import 제거 |

### 1.2 데이터베이스 현황

#### shop_reviews 테이블 (shopping_mall 모듈)

```
모델 파일: shopping_mall/backend/app/models/review.py
테이블명: shop_reviews
ORM: SQLAlchemy 2.0 (sync) + psycopg2 (shopping_mall 모듈)
시드 데이터: 30건 → 더미 추가 후 10,000건
```

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | Integer, PK | 리뷰 고유 ID |
| `product_id` | Integer, FK → shop_products.id | 상품 ID (42개 상품) |
| `user_id` | Integer, FK → shop_users.id | 작성자 ID (5명) |
| `rating` | Float | 평점 (1~5) |
| `content` | Text, nullable | 리뷰 텍스트 |
| `images` | Text, nullable | 이미지 URL |
| `created_at` | DateTime | 작성 일시 |

**주의사항**: shopping_mall은 `psycopg2` (sync), backend/app은 `asyncpg` (async) — 다른 드라이버 사용. 직접 모델 import가 불가능하므로 SQL 직접 쿼리 또는 별도 어댑터 필요.

#### 현재 리뷰 분석 테이블 (backend 모듈)

| 테이블 | 모델 | 역할 |
|--------|------|------|
| `review_analyses` | ReviewAnalysis | 분석 실행 기록 (감성 요약, 키워드, LLM 정보) |
| `review_sentiments` | ReviewSentiment | 개별 리뷰 감성 분석 캐시 |

### 1.3 임베딩 현황

| 항목 | 현재 값 |
|------|---------|
| 컬렉션명 | `reviews_llama` |
| 임베딩 모델 | Ollama `nomic-embed-text` (커스텀 `OllamaEmbeddingFunction`) |
| 벡터 차원 | 4096 (llama 기반) |
| 유사도 메트릭 | cosine |
| 한국어 지원 | 코드에 "nomic-embed-text는 한국어 미지원" 주석 → Phase 1에서 검증 및 최적화 |

### 1.4 LLM 설정 현황

| 항목 | 현재 값 |
|------|---------|
| LLM_PROVIDER | `ollama` |
| LLM_MODEL | `llama3.1:8b` |
| OLLAMA_BASE_URL | `http://localhost:11434` |
| REVIEW_ANALYSIS_BATCH_SIZE | 40 |
| REVIEW_ANALYSIS_MAX_RETRIES | 2 |

---

## 2. 요구사항

### 2.1 기능 요구사항

#### FR-01: Mock 제거 + 더미데이터 생성 + DB 연동 (우선순위: 높음)

| 항목 | 내용 |
|------|------|
| **현재** | Mock 500건 하드코딩 (`MOCK_REVIEWS` in `api/review_analysis.py`), shop_reviews 30건 시드 |
| **목표** | Mock 데이터 완전 제거 + 더미데이터 10,000건 생성 스크립트 + shop_reviews DB에서 직접 조회 |
| **더미데이터 구성** | 긍정(positive) 45% = 4,500건, 중립(neutral) 45% = 4,500건, 부정(negative) 10% = 1,000건. 기존 30건 유지 + 9,970건 추가 |
| **기술적 과제** | shopping_mall(sync psycopg2)과 backend(async asyncpg)가 다른 DB 드라이버 사용 |
| **해결 방안** | 1) 더미데이터 생성 스크립트(`scripts/seed_reviews.py`) 작성 — shop_products/shop_users 참조하여 현실적 리뷰 생성. 2) `asyncpg`로 `shop_reviews` 직접 SELECT (같은 DB 공유). 3) `MOCK_REVIEWS` 변수 및 관련 코드 완전 삭제 |
| **구현 위치** | 신규: `scripts/seed_reviews.py`, 수정: `review_rag.py`, `api/review_analysis.py`, `schemas/review_analysis.py` |

#### FR-02: 멀티테넌트 리뷰 필터링 (우선순위: 높음)

| 항목 | 내용 |
|------|------|
| **현재** | 전체 리뷰 대상 분석만 가능 |
| **목표** | 판매자(farmer)는 자기 상품 리뷰만, 관리자(admin)는 전체 리뷰 접근 |
| **기술적 과제** | shop_reviews.user_id → shop_stores.owner_id → FarmOS users.id 연결 관계 확인 필요 |
| **해결 방안** | JWT에서 user_id 추출 → shop_products에서 해당 판매자 상품 조회 → product_id로 리뷰 필터링. ChromaDB 메타데이터에 `product_id`가 이미 포함되어 있으므로 검색 시 where 필터 적용 |
| **구현 위치** | `api/review_analysis.py`의 각 엔드포인트에 scope 파라미터 확장 |

#### FR-03: 감성분석 정확도 검증 (우선순위: 높음)

| 항목 | 내용 |
|------|------|
| **현재** | 프롬프트 완성, 런타임 테스트 미수행 (SC-02 Partial) |
| **목표** | Ollama llama3.1:8b 환경에서 감성분석 정확도 80%+ 확인 |
| **방법** | 1) 더미 리뷰 50건 샘플링 (생성 시 감성 라벨 포함) → 2) 분석 실행 → 3) 결과 비교 → 4) 프롬프트 튜닝 |
| **비용 고려** | 로컬 Ollama 사용으로 비용 0원. 정확도 미달 시 프롬프트 Few-shot 예시 추가 우선, 그래도 미달 시 OpenRouter 경량 모델(GPT-4o-mini) 폴백 |
| **구현 위치** | `review_analyzer.py`의 `ANALYSIS_PROMPT_TEMPLATE` 수정 (필요 시) |

#### FR-04: 자동 배치 스케줄러 (우선순위: 중간)

| 항목 | 내용 |
|------|------|
| **현재** | GET/PUT `/settings` CRUD만 구현, 실제 스케줄러 없음 (SC-07 Partial) |
| **목표** | 설정된 주기에 맞춰 자동 분석 실행 |
| **확정 기술** | **APScheduler** (독립 실행, cron 표현식 지원, FastAPI와 통합 용이) |
| **트리거** | 주기 기반 (일간 22:00 / 주간 일요일 22:00) + 이벤트 기반 (신규 리뷰 N건 누적) |
| **구현 위치** | 신규 파일 `core/review_scheduler.py` + `main.py` lifespan에 등록 |

#### FR-05: 한국어 임베딩 모델 최적화 (우선순위: 높음 → Phase 1 포함)

| 항목 | 내용 |
|------|------|
| **현재** | `nomic-embed-text` 사용 중이나 "한국어 미지원" 주석 있음. `OllamaEmbeddingFunction`이 실제로 어떤 결과를 내는지 검증 필요 |
| **목표** | 한국어 리뷰 의미 검색 정확도 확인 및 개선 |
| **방법** | 1) 현재 모델로 테스트 쿼리 실행 → 2) Top-5 결과 관련성 평가 → 3) 미달 시 `llama3.1:8b` 임베딩으로 전환 시도 |
| **구현 위치** | `review_rag.py`의 `EMBED_MODEL` 상수 및 `OllamaEmbeddingFunction` |

#### FR-06: 프론트엔드 UX 고도화 (우선순위: 중간)

| 항목 | 내용 |
|------|------|
| **현재** | `ReviewsPage.tsx`에서 API 데이터 없으면 Mock 폴백 (`REVIEWS`, `SENTIMENT_SUMMARY`, `KEYWORD_DATA` 등) |
| **목표** | Mock import 완전 제거, 빈 상태/로딩/에러 UX 구현 |
| **구현 위치** | `ReviewsPage.tsx` 수정, `mocks/reviews.ts` import 제거 |

### 2.2 비기능 요구사항

| ID | 항목 | 요구사항 |
|----|------|---------|
| NFR-01 | **LLM 비용 최소화** | 1회 호출로 3분석 동시 처리 (유지). 배포 시 경량 모델 우선. 배치 40건/1호출 |
| NFR-02 | **DB 호환성** | asyncpg로 shop_reviews 직접 쿼리 (shopping_mall의 psycopg2 모델 미사용) |
| NFR-03 | **응답 시간** | 단건 분석 < 5초, 배치 50건 < 30초, DB 동기화 10,000건 < 30초 |
| NFR-04 | **보안** | 판매자는 자기 상품 리뷰만 접근 (JWT 기반 필터링) |
| NFR-05 | **안정성** | 스케줄러 실패 시 재시도 (최대 2회) + 로그 기록, 수동 실행은 항상 가능 |
| NFR-06 | **대규모 데이터** | 10,000건 임베딩 < 30분, ChromaDB 검색 < 1초 |

---

## 3. 구현 계획

### 3.1 Phase 1: 안정화 + 데이터 기반 전환 (높음 우선순위, 1~2주)

Mock 제거 + 더미데이터 10,000건 + DB 연동 + 임베딩 최적화 + 멀티테넌트 + 감성분석 검증 — 6개 항목을 Phase 1에서 일괄 해결.

| 단계 | 모듈 | 작업 내용 | 수정/신규 파일 | 의존성 |
|:----:|------|----------|-------------|--------|
| **1-1** | 더미데이터 | 10,000건 리뷰 생성 스크립트 (긍정 45%, 중립 45%, 부정 10%) | 신규: `scripts/seed_reviews.py` | 없음 |
| **1-2** | Mock 제거 + DB 연동 | MOCK_REVIEWS 삭제, shop_reviews → ChromaDB 동기화 | `review_rag.py`, `api/review_analysis.py`, `schemas/review_analysis.py` | 1-1 |
| **1-3** | 임베딩 최적화 | 한국어 임베딩 모델 검증 및 최적화 | `review_rag.py` | 1-2 (10,000건 데이터 필요) |
| **1-4** | 멀티테넌트 | JWT 기반 판매자별 리뷰 필터링 | `api/review_analysis.py` | 1-2 |
| **1-5** | 감성분석 검증 | Ollama llama3.1:8b 정확도 80%+ 확인 | `review_analyzer.py` (프롬프트 튜닝 시) | 1-2 |

#### 1-1 상세: 더미데이터 10,000건 생성

```python
# scripts/seed_reviews.py (신규)
"""shop_reviews 더미데이터 10,000건 생성 스크립트.

감성 분포:
  - 긍정 (positive, rating 4-5): 45% = 4,500건
  - 중립 (neutral, rating 3): 45% = 4,500건
  - 부정 (negative, rating 1-2): 10% = 1,000건

기존 30건 시드 데이터 유지 + 9,970건 추가.
shop_products (42개), shop_users (5명) FK 참조.
"""
```

더미데이터 요구사항:
- 기존 shop_reviews 30건 유지 (삭제하지 않음)
- 신규 9,970건 INSERT (총 10,000건)
- `product_id`: shop_products 테이블의 실제 ID 참조 (42개 상품)
- `user_id`: shop_users 테이블의 실제 ID 참조 (5명)
- `content`: 농산물 리뷰 템플릿 기반 자연스러운 한국어 텍스트 (랜덤 조합)
- `rating`: 감성 분포에 맞게 1~5 배정
- `created_at`: 최근 6개월 범위 내 랜덤 날짜

#### 1-2 상세: Mock 제거 + DB 연동

```
[현재 흐름 — 완전 제거]
MOCK_REVIEWS (500건 하드코딩) → review_rag.sync_from_mock() → ChromaDB

[목표 흐름]
shop_reviews (10,000건, PostgreSQL) → review_rag.sync_from_db(db) → ChromaDB
                                       ↑
                             asyncpg로 SELECT * FROM shop_reviews
                             WHERE content IS NOT NULL
```

구현 사항:
1. `api/review_analysis.py`에서 `MOCK_REVIEWS` 변수 및 관련 코드 **완전 삭제**
2. `review_rag.py`에 `sync_from_db(db: AsyncSession)` 추가
   - `SELECT id, product_id, user_id, rating, content, created_at FROM shop_reviews WHERE content IS NOT NULL`
   - 결과를 `embed_reviews()` 형식으로 변환
3. `api/review_analysis.py`의 `embed_reviews` 엔드포인트에서 `source="db"` 를 기본값으로 변경
4. `schemas/review_analysis.py`의 `EmbedRequest.source` 기본값을 `"db"`로 변경

#### 1-3 상세: 임베딩 최적화

1. 현재 nomic-embed-text로 테스트 쿼리 실행 ("포장 불만", "배송 느림", "맛있어요")
2. Top-5 결과 관련성 평가 (precision >= 70% 목표)
3. 미달 시 llama3.1:8b 임베딩 전환 시도
4. 10,000건 임베딩 성능 측정 (목표: < 30분)

#### 1-4 상세: 멀티테넌트

```
[판매자 요청 흐름]
JWT(user_id=farmer01)
  → shop_products WHERE store_id IN (SELECT id FROM shop_stores WHERE owner_id = 'farmer01')
  → product_ids = [1, 5, 12]
  → ChromaDB search(where={"product_id": {"$in": product_ids}})
  → 해당 판매자 상품 리뷰만 반환
```

**참고**: shop_stores 테이블에 owner_id 컬럼이 있는지 확인 필요. 없으면 전체 리뷰 접근으로 시작하고, 추후 매핑 테이블 추가.

#### 1-5 상세: 감성분석 검증

1. 더미 리뷰 50건 샘플링 (생성 시 감성 라벨이 이미 포함됨 — rating 기반)
2. `ReviewAnalyzer.analyze_batch()` 실행
3. 결과 비교 → 정확도 계산
4. 80% 미달 시: Few-shot 예시 추가 → 재테스트
5. 여전히 미달 시: OpenRouter GPT-4o-mini 폴백 테스트

### 3.2 Phase 2: 자동화 (중간 우선순위, 2~3주)

| 단계 | 모듈 | 작업 내용 | 수정/신규 파일 | 의존성 |
|:----:|------|----------|-------------|--------|
| **2-1** | 스케줄러 | APScheduler 기반 자동 배치 분석 | 신규: `core/review_scheduler.py`, 수정: `main.py` | Phase 1 완료 |
| **2-2** | 개별 분석 조회 | GET /analysis/{id} 엔드포인트 | `api/review_analysis.py` | 없음 |

#### 2-1 상세: APScheduler 스케줄러 (확정)

```python
# core/review_scheduler.py (신규)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler = AsyncIOScheduler()

async def scheduled_analysis():
    """설정된 주기에 맞춰 자동 분석 실행."""
    # 1. DB에서 신규 리뷰 동기화
    # 2. 분석 실행
    # 3. 결과 저장

def start_scheduler():
    """FastAPI lifespan에서 호출."""
    scheduler.add_job(scheduled_analysis, CronTrigger(hour=22))  # 매일 22시
    scheduler.start()
```

### 3.3 Phase 3: UX 고도화 (중간 우선순위, 3~4주)

| 단계 | 모듈 | 작업 내용 | 수정 파일 | 의존성 |
|:----:|------|----------|----------|--------|
| **3-1** | Mock 폴백 제거 | ReviewsPage에서 Mock import/폴백 로직 제거 | `ReviewsPage.tsx` | Phase 1 완료 |
| **3-2** | 빈 상태 UX | 분석 결과 없을 때 안내 UI | `ReviewsPage.tsx` | 3-1 |
| **3-3** | 에러 UX | API 에러 시 재시도 안내 | `ReviewsPage.tsx` | 3-1 |

---

## 4. 기술 결정 사항

### 4.1 확정 사항

| 결정 | 선택 | 근거 |
|------|------|------|
| DB 접근 방식 | asyncpg raw SQL (text()) | shopping_mall ORM과 backend ORM이 다른 드라이버 사용. 같은 DB이므로 SQL 직접 쿼리가 가장 단순 |
| LLM 모델 (개발) | Ollama llama3.1:8b | 비용 0원, 이미 설정됨. 사용자 비용 우선 정책 |
| LLM 모델 (배포) | OpenRouter GPT-4o-mini | 가장 저렴한 클라우드 옵션 (~$0.15/1M tokens) |
| 배치 크기 | 40건/1호출 (현재 설정 유지) | config.py에 이미 설정됨 |
| 임베딩 모델 | nomic-embed-text (현재) → Phase 1에서 검증 후 결정 | 한국어 미지원 시 llama3.1:8b 전환 |
| 스케줄러 | **APScheduler** (확정) | cron 지원, 독립 실행, AsyncIOScheduler로 FastAPI 호환 |
| 더미데이터 | 10,000건 (긍정 45%, 중립 45%, 부정 10%) | 실전 검증을 위한 현실적 규모 |
| Mock 데이터 | **완전 제거** | Phase 1에서 MOCK_REVIEWS 삭제, DB 연동으로 대체 |

### 4.2 사용자 확인 필요 사항

| 항목 | 권장안 | 결정 기준 |
|------|--------|----------|
| 멀티테넌트 매핑 | shop_stores.owner_id 기반 | shop_stores 테이블 구조에 따라 결정 |

---

## 5. 의존성 그래프

```
[Phase 1]
  1-1 (더미데이터 생성)
    ↓
  1-2 (Mock 제거 + DB 연동)
    ├──→ 1-3 (임베딩 최적화)  ←  10,000건 데이터 필요
    ├──→ 1-4 (멀티테넌트)
    └──→ 1-5 (감성분석 검증)

[Phase 2]
  2-1 (APScheduler 스케줄러)  ←  Phase 1 완료
  2-2 (개별 분석 조회)  ←  없음 (독립)

[Phase 3]
  FR-06 (UX 고도화)  ←  Phase 1 완료
```

---

## 6. 리스크 및 대응

| Risk | Impact | Probability | Mitigation |
|------|:------:|:-----------:|------------|
| shop_reviews ↔ asyncpg 호환 문제 | 중 | 낮 | 같은 PostgreSQL DB이므로 raw SQL로 해결 가능 |
| shop_stores에 owner_id 없음 | 중 | 중 | 우선 전체 리뷰 접근으로 시작, 추후 매핑 테이블 추가 |
| nomic-embed-text 한국어 정확도 부족 | 중 | 중 | llama3.1:8b 임베딩 전환 시도. 또는 multilingual-e5-large 등 대안 |
| Ollama 감성분석 정확도 80% 미달 | 높 | 중 | Few-shot 프롬프트 → OpenRouter GPT-4o-mini 폴백 |
| 10,000건 임베딩 시간 초과 (> 30분) | 중 | 중 | 청크 단위 임베딩 (100건씩), 백그라운드 작업으로 실행 |
| APScheduler + FastAPI 통합 이슈 | 낮 | 낮 | AsyncIOScheduler는 FastAPI asyncio 루프와 호환 |
| 더미데이터 FK 충돌 | 낮 | 낮 | 생성 전 shop_products/shop_users 실제 ID 조회 후 참조 |
| Mock 제거 후 빈 상태 UX 미비 | 낮 | 중 | Phase 3에서 빈 상태 컴포넌트 구현 |

---

## 7. Success Criteria

| SC | 기준 | 측정 방법 | Phase |
|----|------|----------|:-----:|
| SC-01 | 더미데이터 10,000건이 shop_reviews에 투입된다 | `SELECT COUNT(*) FROM shop_reviews` == 10,000 | 1 |
| SC-02 | MOCK_REVIEWS 코드가 완전 제거된다 | `api/review_analysis.py`에 MOCK_REVIEWS 변수 없음 | 1 |
| SC-03 | shop_reviews 데이터가 ChromaDB에 동기화된다 | `source="db"` 임베딩 후 `get_count()` >= 10,000 | 1 |
| SC-04 | 한국어 의미 검색 Top-5 precision >= 70% | "포장 불만" 검색 시 관련 리뷰 5개 중 3.5개+ | 1 |
| SC-05 | 감성분석 정확도 80%+ (Ollama llama3.1:8b) | 라벨링 50건 대비 일치율 | 1 |
| SC-06 | 판매자가 자기 상품 리뷰만 분석 결과를 볼 수 있다 | 다른 판매자 리뷰 접근 시 빈 결과 반환 | 1 |
| SC-07 | 자동 배치 분석이 설정 주기에 맞춰 실행된다 | 스케줄러 로그에서 자동 실행 확인 | 2 |
| SC-08 | 프론트엔드가 Mock 없이 실제 API 데이터로만 동작한다 | `mocks/reviews.ts` import 0건 | 3 |

---

## 8. 구현 산출물 예상

### 신규 파일

| 파일 | Phase | 역할 |
|------|:-----:|------|
| `scripts/seed_reviews.py` | 1 | 더미데이터 10,000건 생성 스크립트 |
| `backend/app/core/review_scheduler.py` | 2 | APScheduler 기반 자동 배치 스케줄러 |

### 수정 파일

| 파일 | Phase | 변경 내용 |
|------|:-----:|----------|
| `backend/app/core/review_rag.py` | 1 | `sync_from_db()` 메서드 추가 |
| `backend/app/api/review_analysis.py` | 1 | MOCK_REVIEWS 완전 삭제, DB 연동, 멀티테넌트 필터 |
| `backend/app/schemas/review_analysis.py` | 1 | EmbedRequest source 기본값 "db" |
| `backend/app/core/review_analyzer.py` | 1 | 프롬프트 튜닝 (정확도 미달 시) |
| `backend/app/main.py` | 2 | 스케줄러 lifespan 등록 |
| `frontend/src/modules/reviews/ReviewsPage.tsx` | 3 | Mock 폴백 제거, UX 개선 |

### 변경 없는 파일 (기존 구현 유지)

- `backend/app/core/llm_client_base.py` — LLM 추상화 완성
- `backend/app/core/trend_detector.py` — 트렌드/이상 탐지 완성
- `backend/app/core/review_report.py` — PDF 리포트 완성
- `backend/app/models/review_analysis.py` — DB 모델 완성
- `frontend/src/hooks/useReviewAnalysis.ts` — API 훅 완성
- `frontend/src/modules/reviews/RAGSearchPanel.tsx` — RAG 검색 완성
- `frontend/src/modules/reviews/AnalysisSettingsModal.tsx` — 설정 모달 완성

---

## 9. 용어 정리

| 용어 | 설명 |
|------|------|
| **Mock 폴백** | API 응답이 없을 때 하드코딩된 Mock 데이터로 대체하는 로직 |
| **멀티테넌트** | 하나의 시스템에서 여러 사용자(판매자)가 각자의 데이터만 접근하는 구조 |
| **sync_from_db** | PostgreSQL shop_reviews → ChromaDB 벡터 저장소로 데이터 동기화 |
| **APScheduler** | Python 비동기 작업 스케줄러. cron 표현식으로 주기적 실행 가능 |
| **더미데이터** | 테스트/검증 목적으로 생성한 가상의 리뷰 데이터 (10,000건, 감성 분포 제어) |
