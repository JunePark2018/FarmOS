# IoT AI Agent 구현 기록

> **작성일**: 2026-04-07
> **상태**: 구현 완료 (버그 수정 포함)

---

## 1. 개요

IoT 센서값 + 기상청 API를 종합 분석하여 환기/관수/조명/차광을 자동 제어하는 AI Agent 시스템.
모든 제어는 **가상 시뮬레이션** (실제 하드웨어 제어 없음).

---

## 2. 아키텍처

```
ESP8266 (DHT11 + CdS, 30초 간격)
    │ HTTP POST
    v
릴레이 서버 (N100:9000, Docker)
    ├─ store.py: 센서 저장 + 토양습도 추정
    ├─ sensor_filter.py: 조도센서 이상값 필터링
    ├─ ai_agent.py: 규칙 판단 + LLM 종합 판단
    ├─ weather_client.py: 기상청 API (또는 mock)
    └─ /api/v1/ai-agent/* 엔드포인트
          │ 30초 폴링
          v
    프론트엔드 대시보드 (AIAgentPanel)
```

---

## 3. 2단계 판단 구조

### 1단계: 규칙 기반 (항상 실행, LLM 비용 0)

#### 이상 상황 발동

| 조건 | 제어 | 우선순위 |
|------|------|---------|
| 온도 > 35C | 창문 100%, 팬 3000 RPM | emergency |
| 온도 30~35C + 외부 < 내부 | 자연환기 (비율 계산) | high |
| 습도 > 90% | 팬 1500 RPM, 창문 50%+ | high |
| 강수 감지 | 창문 닫기 | high |
| 토양수분 < 30% | 긴급 관수 3L | emergency |
| 야간 + 외부 < 5C | 보온커튼 100%, 창문 닫기 | emergency |
| 야간 + 외부 < 10C | 보온커튼 70%+ | medium |
| 야간 | 조명 OFF | low |
| 주간 + 조도 < 5,000 lux | 보광등 60% | medium |
| 주간 + 조도 > 70,000 lux | 차광막 50% | medium |

#### 정상 복귀

| 조건 | 제어 | 비고 |
|------|------|------|
| 온도 ≤ 30C + 습도 ≤ 80% | 환기 해제 (창문 0%, 팬 0) | 창문/팬 둘 다 체크 |
| 강수 종료 + 온도/습도 높음 | 창문 재개방 | 이력에서 강수 판단 확인 후만 |
| 토양수분 ≥ 50% | 관수 밸브 닫힘 | |
| 주간 | 보온커튼 해제 | |
| 주간 + 조도 ≥ 30,000 lux | 보광등 OFF | |
| 조도 ≤ 50,000 lux | 차광막 해제 | |

### 2단계: LLM (GPT-5-nano, 5분 간격)

- 센서값 5% 이상 변화 시에만 호출
- 긴급 아닌 미세 조정, 기상 예보 반영, 작물별 양액 배합
- `OPENROUTER_API_KEY` 미설정 시 건너뜀

---

## 4. 조도센서 불안정 대응 (sensor_filter.py)

KY-018 LDR이 간헐적으로 0값을 반환하는 문제 대응:

1. **이동평균 필터**: 최근 10회 값의 이동평균 대비 ±80% 급변 → suspicious
2. **연속 0값 카운트**:
   - 3회 미만 + 낮시간 → 이전 유효값으로 대체 (suspicious)
   - 3회 이상 + 낮시간 → 센서 장애 판정 (unreliable)
   - 야간 + 0 → 정상
3. **신뢰도 플래그**: reliable / suspicious / unreliable
4. LLM 프롬프트에 신뢰도 정보 포함 → 판단 가중치 조절

---

## 5. 기상 데이터 (weather_client.py)

- **KMA_DECODING_KEY 있음**: 기상청 초단기실황 API 호출 (10분 캐싱)
- **없음**: 센서 데이터 기반 mock 기상 데이터 자동 생성
- 격자좌표 변환 함수 포함 (Lambert Conformal Conic)

---

## 6. 파일 구조

### 릴레이 서버 (iot_relay_server/app/)

| 파일 | 역할 |
|------|------|
| `config.py` | 설정 (AI_AGENT_MODEL, KMA 키 등) |
| `sensor_filter.py` | 센서 이상값 필터링 |
| `weather_client.py` | 기상청 API 클라이언트 |
| `ai_agent_prompts.py` | LLM 시스템/사용자 프롬프트 |
| `ai_agent.py` | Agent 엔진 (규칙+LLM, 상태관리, 이력) |
| `schemas.py` | CropProfileIn, OverrideIn 추가 |
| `store.py` | 토양습도 추정 (기존) |
| `main.py` | Agent 라우터 + 센서수신 시 Agent 호출 |

### 로컬 백엔드 (backend/app/)

릴레이 서버와 동일한 구조로 `core/` 하위에 배치.
`api/ai_agent.py`는 JWT 인증 포함.

### 프론트엔드 (frontend/src/)

| 파일 | 역할 |
|------|------|
| `types/index.ts` | AIControlState, AIDecision, CropProfile 타입 |
| `hooks/useAIAgent.ts` | 30초 폴링, toggle/updateProfile/override |
| `modules/iot/AIAgentPanel.tsx` | 4대 제어 카드 + 판단 이력 + ON/OFF |
| `modules/iot/CropProfileModal.tsx` | 프리셋 5종 + 자유 입력 모달 |
| `modules/iot/IoTDashboardPage.tsx` | AIAgentPanel 통합 |

---

## 7. API 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/v1/ai-agent/status` | Agent 상태 + 제어값 + 최신 판단 |
| GET | `/api/v1/ai-agent/decisions?limit=20` | 판단 이력 |
| POST | `/api/v1/ai-agent/toggle` | ON/OFF 전환 |
| GET | `/api/v1/ai-agent/crop-profile` | 작물 프로필 + 프리셋 |
| PUT | `/api/v1/ai-agent/crop-profile` | 작물 프로필 수정 |
| POST | `/api/v1/ai-agent/override` | 수동 오버라이드 |
| POST | `/api/v1/ai-agent/test-trigger` | 디버그: 수동 트리거 |

---

## 8. 작물 프리셋

| 작물 | 생육단계 | 적정온도 | 적정습도 | 일조 | N:P:K |
|------|---------|---------|---------|------|-------|
| 토마토 | 개화기 | 20~28C | 60~80% | 14h | 1.0:1.2:1.5 |
| 딸기 | 착과기 | 15~25C | 60~75% | 12h | 0.8:1.0:1.5 |
| 상추 | 영양생장기 | 15~22C | 60~70% | 12h | 1.5:0.8:1.0 |
| 고추 | 개화기 | 22~30C | 60~75% | 14h | 1.2:1.0:1.3 |
| 오이 | 영양생장기 | 20~28C | 70~85% | 13h | 1.3:1.0:1.2 |

---

## 9. 환경 설정 (.env)

```
# 기존
IOT_API_KEY=farmos-iot-default-key
SOIL_MOISTURE_LOW=55.0
SOIL_MOISTURE_HIGH=70.0

# AI Agent
OPENROUTER_API_KEY=          # 넣으면 LLM 판단 활성화
AI_AGENT_MODEL=openai/gpt-5-nano
AI_AGENT_LLM_INTERVAL=300   # LLM 호출 최소 간격 (초)

# 기상청 API (선택)
KMA_DECODING_KEY=            # 넣으면 실제 기상 데이터
FARM_NX=84                   # 격자좌표
FARM_NY=106
```

---

## 10. 발견된 버그 및 수정 이력

| 문제 | 원인 | 수정 |
|------|------|------|
| AI Agent가 아예 동작 안 함 | `store.py`(동기)에서 `asyncio.ensure_future()` 호출 실패, `except: pass`로 무시됨 | `main.py`의 async 엔드포인트에서 `await` 직접 호출로 변경 |
| 습도 정상인데 환기 계속 유지 | 정상 복귀 로직 없음 (발동만 있고 해제 없음) | 모든 제어 항목에 정상 복귀 규칙 추가 |
| 창문만 열린 상태 복귀 안 됨 | 복귀 조건이 `fan_speed > 0`만 체크 | `fan_speed > 0 OR window_open_pct > 0`으로 변경 |
| 강수 복귀 오발동 | 강수 이력 없는데도 매번 "강수 종료" 판단 실행 | 최근 이력에서 강수 판단이 있었을 때만 복귀 |
| `daily_total_L` 무한 누적 | 일일 리셋 로직 없음 | 자정(KST) 기준 0으로 리셋 |
| `soil_moisture` None 비교 에러 | `dict.get(key, 50)`이 값이 `None`일 때 기본값 적용 안 됨 | `or 50`으로 변경 (3곳) |
| AI Agent에 토양습도 추정값 미반영 | `sensors_dict` 원본(None)이 Agent에 전달됨 | `get_latest()`로 store 추정값 반영된 데이터 전달 |
| 프론트엔드 AI Agent 패널 안 보임 | `credentials: 'include'`가 릴레이 서버 CORS와 충돌 + API 실패 시 `return null` | `credentials: 'omit'` + 연결 대기 UI 표시 |
| 조명/차광 규칙 없음 | LLM에만 의존 | 조도 기반 보광등/차광막 규칙 추가 |

---

## 11. LLM 비용 관리

| 항목 | 전략 |
|------|------|
| 모델 | GPT-5-nano (경량, 저비용) |
| 호출 빈도 | 5분 간격 제한 + 센서값 5% 이상 변화 시에만 |
| 규칙 우선 | 긴급 상황은 LLM 없이 규칙으로 즉시 처리 |
| 키 미설정 시 | 규칙만으로 동작 (LLM 비용 0) |
| 예상 호출량 | 일 50~150회 (센서 변화량에 따라) |

---

## 12. 배포 방법

```bash
# N100 서버에서
cd iot_relay_server
git pull
docker-compose up -d --build
```

Docker 재빌드 시 새 파일(sensor_filter.py, weather_client.py, ai_agent.py 등)이 자동 포함됨.
