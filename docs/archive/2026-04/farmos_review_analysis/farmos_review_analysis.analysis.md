# FarmOS 리뷰 분석 (farmos_review_analysis) — Gap Analysis

> **Feature**: farmos_review_analysis Phase 1
> **Date**: 2026-04-13
> **Phase**: Check (Gap 분석)
> **Design**: `docs/02-design/features/farmos_review_analysis.design.md` (Option C)
> **Plan**: `docs/01-plan/features/farmos_review_analysis.plan.md` v1.1

---

## Context Anchor

| Anchor | Content |
|--------|---------|
| **WHY** | Mock 의존성 제거 + 10,000건 더미데이터 기반 실전 검증 + 한국어 임베딩 최적화 |
| **WHO** | 농업인 판매자 + 관리자 |
| **RISK** | 10,000건 임베딩 성능, 한국어 유사도 정확도, ORM 호환성, LLM 비용 |
| **SUCCESS** | Mock 제거, DB 10,000건 동기화, 임베딩 한국어 검증, 멀티테넌트, 감성분석 80%+ |
| **SCOPE** | Phase 1 (6항목): DB연동 + Mock제거 + 더미데이터 + 멀티테넌트 + 감성분석검증 + 임베딩최적화 |

---

## 1. Structural Match (파일 존재 + 라우트 커버리지)

### 1.1 파일 존재 확인

| Design 파일 | 존재 | Lines | 비고 |
|------------|:----:|:-----:|------|
| `scripts/seed_reviews.py` | O | 290 | 신규. 더미 10,000건 생성 |
| `backend/app/core/review_rag.py` | O | 484 | sync_from_db() +80줄 추가 |
| `backend/app/api/review_analysis.py` | O | 432 | MOCK 삭제(-400), DB 연동(+40) |
| `backend/app/schemas/review_analysis.py` | O | 165 | source 기본값 "db" |
| `scripts/verify_sentiment.py` | O | 200 | 보너스 (Design 미���시) |
| `scripts/verify_embedding.py` | O | 141 | 보너스 (Design 미명시) |
| `core/review_scheduler.py` | X | - | Phase 2 범위 (정상) |

### 1.2 API 라우트 커버리지

| Design 엔드포인트 | 구현 | Line | 비고 |
|-------------------|:----:|:----:|------|
| `POST /reviews/embed` | O | 104 | DB 연동 완료 |
| `GET /reviews/embed/stream` | O | 120 | SSE DB 스트리밍 |
| `GET /reviews/analyze/stream` | O | 135 | SSE DB 자동 동기화 |
| `POST /reviews/analyze` | O | 202 | DB 자동 동기화 |
| `GET /reviews/analysis` | O | 280 | 기존 유지 |
| `POST /reviews/search` | O | 318 | DB 자동 동기화 |
| `GET /reviews/trends` | O | 344 | 기존 유지 |
| `GET /reviews/report/pdf` | O | 369 | 기존 유지 |
| `GET /reviews/settings` | O | 416 | 기존 유지 |
| `PUT /reviews/settings` | O | 422 | 기존 유지 |

**Structural Score: 100%** (10/10 라우트, 6/6 Phase 1 파일)

---

## 2. Functional Depth (로직 완성도)

### 2.1 Mock 제거 — 100%

| 항목 | 상태 |
|------|:----:|
| MOCK_REVIEWS 변수 삭제 (~400줄) | O |
| sync_from_mock() 참조 3곳 → sync_from_db()로 전환 | O |
| Mock 폴백 로직 제거 (analyze, search, embed) | O |
| trends Mock 폴백 → 빈 응답 | O |

### 2.2 DB 연동 — 90%

| 항목 | 상태 | 비고 |
|------|:----:|------|
| sync_from_db() 구현 | O | asyncpg raw SQL |
| sync_from_db_chunked() 구현 | O | SSE 진행률 |
| 중복 임베딩 방지 | O | embed_reviews() 내부에서 처리 |
| 에러 시 partial 복구 | X | 전체 실패 시 복구 로직 없음 |

### 2.3 더미데이터 — 95%

| 항목 | 상태 |
|------|:----:|
| 10,000건 (기존 30 + 신규 9,970) | O |
| 감성 분포 (45/45/10) | O |
| 42개 상품 FK 참조 | O |
| 5명 유저 FK 참조 | O |
| 농산물 템플릿 80개 (30+30+20) | O |
| random.seed(42) 재현성 | O |
| shopping_mall ORM import 의존 | Issue (G-03) |

### 2.4 멀티테넌트 — 50%

| 항목 | 상태 | 비고 |
|------|:----:|------|
| `_get_seller_product_ids()` 헬퍼 | O | 구조 준비 |
| TODO: owner_id SQL 주석 | O | 확장 가능 |
| 엔드포인트에서 호출 | X | **Gap G-01** |
| `get_reviews_by_products()` (Design §4.2) | X | **Gap G-02** |

### 2.5 검증 도구 — 85%

| 항목 | 상태 | 비고 |
|------|:----:|------|
| verify_sentiment.py (50건 라벨, accuracy 계산) | O | |
| verify_embedding.py (5개 쿼리, precision 계산) | O | |
| 런타임 실행 검증 | 대기 | Ollama + DB 필요 |

**Functional Score: 85%**

---

## 3. API Contract (Design ↔ 구현)

| Design 스펙 | 구현 | 일치 |
|------------|------|:----:|
| POST /embed → source="db" 기본 | DB만 지원 (source 필드 유지) | O |
| GET /embed/stream → SSE 진행률 | sync_from_db_chunked 사용 | O |
| POST /analyze → ChromaDB 조회 후 LLM 분석 | DB 자동 동기화 + 분석 | O |
| POST /search → RAG 의미 검색 | DB 자동 동기화 + 검색 | O |
| GET /trends → 트렌드 데이터 | Mock 폴백 제거, 빈 응답 | O |
| EmbedResponse.source 필드 | "db" 반환 | O |
| 멀티테넌트 product_id 필터 | 구조만 준비, 미적용 | 부분 |

**Contract Score: 90%**

---

## 4. Match Rate 계산

```
Static Only Formula:
  Structural × 0.2 + Functional × 0.4 + Contract × 0.4

  = (100% × 0.2) + (85% × 0.4) + (90% × 0.4)
  = 20 + 34 + 36
  = 90%
```

**Overall Match Rate: 90%**

---

## 5. Success Criteria 평가

| SC | 기준 | 상태 | 근거 |
|----|------|:----:|------|
| SC-01 | 더미 10,000건 생성 스크립트 | ✅ Met | scripts/seed_reviews.py, 9,970건 생성 로직 완성 |
| SC-02 | MOCK_REVIEWS 코드 완전 제거 | ✅ Met | 815줄→432줄, MOCK_REVIEWS grep 0건 |
| SC-03 | DB → ChromaDB 동기화 | ✅ Met | sync_from_db(), sync_from_db_chunked() 구현 |
| SC-04 | 한국어 임베딩 검증 도구 | ✅ Met | scripts/verify_embedding.py, 5개 테스트 쿼리 |
| SC-05 | 감성분석 검증 도구 | ✅ Met | scripts/verify_sentiment.py, 50건 라벨 + accuracy |
| SC-06 | 멀티테넌트 구조 | ⚠️ Partial | 헬퍼 함수 존재, 엔드포인트 미적용 |

**Success Rate: 5/6 Met, 1/6 Partial = 83%**

---

## 6. Gap 리스트

### Important (3건)

| # | Gap | 파일 | 수정 방안 |
|:-:|-----|------|----------|
| G-01 | 멀티테넌트 헬퍼가 엔드포인트에서 호출되지 않음 | `api/review_analysis.py` | analyze, search에 `seller_id: str | None = Query(None)` 추가 및 `_get_seller_product_ids()` 호출 |
| G-02 | Design §4.2의 `get_reviews_by_products()` 미구현 | `review_rag.py` | ChromaDB where 필터로 product_id 기반 조회 메서드 추가 |
| G-03 | seed_reviews.py가 shopping_mall ORM 패키지 import 의존 | `scripts/seed_reviews.py` | psycopg2 직접 연결로 변경, .env에서 DB URL 읽기 |

### Minor (4건)

| # | Gap | 파일 | 수정 방안 |
|:-:|-----|------|----------|
| G-04 | sync_from_db()가 전체 결과를 메모리 로드 (대규모 시 이슈) | `review_rag.py` | LIMIT/OFFSET 페이징 (현재 10,000건��� 문제 없음) |
| G-05 | review_rag.py에 sync_from_mock() 레거시 잔존 | `review_rag.py` | 데드코드 삭제 |
| G-06 | verify_sentiment.py 부정 리뷰 5건 불균형 | `scripts/verify_sentiment.py` | 15건으로 확대 |
| G-07 | EmbedRequest에 mock source 분기 불완전 정리 | `schemas/review_analysis.py` | source 필드 제거 또는 Literal["db"]로 제한 |

---

## 7. 심각도 ���약

| 심각도 | 건수 | Match Rate 영향 |
|--------|:----:|:---------------:|
| Critical | 0 | - |
| Important | 3 | -10% (현재 90%) |
| Minor | 4 | -3% |

---

## 8. Checkpoint 5 — 수정 방향 제안

### 권장: Important 3건 수정

**G-01 + G-02 (멀티테넌트 완성)**:
- `review_rag.py`에 `get_reviews_by_products()` 추가
- `api/review_analysis.py`의 search, analyze에 seller_id 파라미터 추가
- 예상 작업량: ~30줄 추가

**G-03 (seed 의존성 해소)**:
- psycopg2 직접 사용, `DATABASE_URL` 환경변수에서 DB URL 읽기
- 예상 작업량: import 부분 ~10줄 수정

### 수정 후 예상 Match Rate

```
G-01~G-03 수정 시:
  Structural: 100% (변화 없음)
  Functional: 85% → 93%
  Contract: 90% → 97%

  = (100 × 0.2) + (93 × 0.4) + (97 × 0.4)
  = 20 + 37.2 + 38.8
  = 96%
```

**예상 Match Rate: 90% → 96%**
