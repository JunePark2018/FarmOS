# IoT AI Agent 스마트팜 자동 제어 Planning Document

> **Summary**: AI Agent가 실시간 센서값 + 기상청 API 데이터를 종합 분석하여 환기, 관수/양액, 조명, 차광/보온을 자동 제어
>
> **Project**: FarmOS - IoT AI Agent Automation
> **Version**: 0.1.0
> **Author**: clover0309
> **Date**: 2026-04-07
> **Status**: Draft
> **Prerequisites**: 기존 IoT Relay Server 정상 동작, 기상청 API 키

---

## Executive Summary

| Perspective | Content |
|-------------|---------|
| **Problem** | 현재 IoT 시스템은 센서값 모니터링 + 토양습도 기반 단순 관수 알림만 제공. 환기/조명/차광 등은 수동 판단 필요 |
| **Solution** | AI Agent가 센서 4종(온도, 습도, 조도, 토양수분) + 기상청 예보를 종합 분석하여 4대 제어 항목을 자동 판단/실행 |
| **Function/UX Effect** | 대시보드에서 AI 판단 근거와 제어 이력을 실시간 확인, 수동 오버라이드 가능 |
| **Core Value** | 1인 농업인이 24시간 온실을 최적 환경으로 유지할 수 있는 AI 기반 자동화 |

---

## 1. 현재 시스템 분석

### 1.1 기존 IoT 아키텍처

```
ESP8266 (DHT11 + CdS + 토양수분)
    | HTTP POST (30초 간격)
    v
IoT Relay Server (N100:9000, FastAPI)
    | GET (30초 폴링)
    v
Frontend Dashboard (React)
```

### 1.2 현재 수집 센서

| 센서 | 측정값 | 범위 | 비고 |
|------|--------|------|------|
| DHT11 | 온도 | -40~80 C | 직접 측정 |
| DHT11 | 습도 | 0~100 % | 직접 측정 |
| KY-018 LDR | 조도 | 0~100,000 Lux | 아날로그 변환 |
| 토양수분 | 수분 | 20~85 % | 서버 추정값 (실 센서 미장착) |

### 1.3 현재 자동화 수준

- 토양수분 < 55% 시 관수 알림 + 자동 이벤트 생성 (밸브 열림)
- 습도 > 90% 시 주의 알림
- **실제 하드웨어 제어 없음** (가상 시뮬레이션)

---

## 2. AI Agent 설계

### 2.1 전체 아키텍처

```
                    ┌─────────────────────┐
                    │   기상청 API (KMA)    │
                    │  - 초단기실황/예보     │
                    │  - 단기예보           │
                    └─────────┬───────────┘
                              │
┌──────────────┐              │          ┌─────────────────────┐
│  ESP8266     │              │          │   AI Agent Engine    │
│  센서 데이터  │──────────────┼─────────>│                     │
│  (30초 간격)  │              │          │  1. 데이터 수집/통합  │
└──────────────┘              │          │  2. 상태 분석         │
                              │          │  3. 규칙 + LLM 판단  │
                              └─────────>│  4. 제어 명령 생성    │
                                         │  5. 실행 + 로깅      │
                                         └─────────┬───────────┘
                                                   │
                          ┌────────────────────────┼────────────────────────┐
                          │                        │                        │
                          v                        v                        v
                   ┌─────────────┐         ┌─────────────┐         ┌─────────────┐
                   │  제어 명령    │         │  대시보드     │         │  알림/로그    │
                   │  (가상 실행)  │         │  (실시간)     │         │  (히스토리)   │
                   └─────────────┘         └─────────────┘         └─────────────┘
```

### 2.2 AI Agent 판단 흐름

```
[30초마다 실행]
    │
    ├─ (1) 센서 데이터 수집 (Relay Server GET /sensors/latest)
    ├─ (2) 기상청 데이터 수집 (캐싱: 10분 간격)
    │
    v
[데이터 통합 & 정규화]
    │
    v
[규칙 기반 1차 판단] ──────────────────────────────────┐
    │                                                  │
    ├─ 긴급 상황 (온도 > 40C, 습도 > 95% 등)           │
    │   → 즉시 제어 명령 실행                           │
    │                                                  │
    ├─ 일반 상황                                       │
    │   → LLM 기반 2차 판단                            │
    │                                                  │
    v                                                  │
[LLM 종합 판단]                                        │
    │  - 현재 센서값 + 기상 예보 + 작물 특성 + 시간대     │
    │  - JSON 형태로 제어 명령 출력                      │
    │                                                  │
    v                                                  │
[제어 명령 실행 (가상)]  <─────────────────────────────┘
    │
    ├─ 환기: 창문 개방도(%), 팬 속도(RPM)
    ├─ 관수: 급수량(L), 양액 배합비
    ├─ 조명: ON/OFF, 밝기(%)
    └─ 차광/보온: 차광막(%), 보온커튼(%)
    │
    v
[실행 로그 저장 + 대시보드 업데이트]
```

### 2.3 판단 근거 구조 (LLM 프롬프트 설계)

AI Agent가 판단할 때 LLM에 전달하는 컨텍스트:

```json
{
  "current_sensors": {
    "temperature": 28.5,
    "humidity": 78.0,
    "light_intensity": 45000,
    "soil_moisture": 42.0,
    "timestamp": "2026-04-07T14:30:00"
  },
  "weather_forecast": {
    "current": { "temp": 26, "humidity": 65, "sky": "맑음", "wind": 3.2 },
    "next_3h": { "temp": 24, "humidity": 70, "precipitation_prob": 20 },
    "next_6h": { "temp": 20, "humidity": 80, "precipitation_prob": 60 },
    "next_12h": { "temp": 15, "humidity": 85, "precipitation_prob": 80 }
  },
  "current_controls": {
    "ventilation": { "window_open_pct": 30, "fan_speed": 0 },
    "irrigation": { "last_watered": "2026-04-07T08:00:00", "daily_total_L": 5.2 },
    "lighting": { "status": "off", "brightness_pct": 0 },
    "shading": { "shade_pct": 0, "insulation_pct": 0 }
  },
  "crop_profile": {
    "type": "토마토",
    "growth_stage": "개화기",
    "optimal_temp": [20, 28],
    "optimal_humidity": [60, 80],
    "optimal_light_hours": 14
  },
  "time_context": {
    "local_time": "14:30",
    "sunrise": "06:15",
    "sunset": "19:02",
    "is_daytime": true
  }
}
```

LLM 응답 형태:

```json
{
  "decisions": [
    {
      "control": "ventilation",
      "action": { "window_open_pct": 60, "fan_speed": 1200 },
      "reason": "내부 온도 28.5C가 토마토 적정 상한(28C)에 근접. 외부 온도 26C로 자연환기 효과 기대. 6시간 후 비 예보로 사전에 습도 관리 필요.",
      "priority": "medium",
      "duration_minutes": 30
    },
    {
      "control": "irrigation",
      "action": { "water_amount_L": 2.0, "nutrient_ratio": { "N": 1.0, "P": 0.8, "K": 1.2 } },
      "reason": "토양수분 42%로 부족. 개화기 토마토는 칼륨(K) 비율 높여야 함. 6시간 후 강수 예보 감안하여 적정량만 공급.",
      "priority": "high",
      "duration_minutes": 15
    }
  ],
  "overall_assessment": "온실 내부 온도 상승 추세, 오후 강수 예보 감안하여 환기 강화 및 적정 관수 실시. 차광/보온/조명은 현재 상태 유지.",
  "next_check_interval_sec": 300
}
```

---

## 3. 4대 제어 항목 상세

### 3.1 환기 제어 (Ventilation)

| 항목 | 설명 |
|------|------|
| **제어 대상** | 창문 개방도 (0~100%), 환기 팬 (0~3000 RPM) |
| **주요 판단 요소** | 내부 온도/습도, 외부 온도/습도, 풍속, 강수 예보 |
| **긴급 규칙** | 내부 온도 > 35C → 창문 100% + 팬 최대 |
| **일반 판단** | LLM이 내외부 온도차, 습도, 바람 고려하여 최적값 산출 |

#### 판단 규칙 매트릭스

| 조건 | 창문 | 팬 | 비고 |
|------|------|-----|------|
| 내부온도 > 35C | 100% | MAX | 긴급 냉각 |
| 내부온도 > 30C & 외부 < 내부 | 70~100% | 중속 | 자연환기 우선 |
| 내부습도 > 90% | 50~80% | 중속 | 결로/병해 방지 |
| 외부 강수중 | 닫힘 | 중속 | 빗물 유입 차단, 내부 순환 |
| 외부 풍속 > 10m/s | 30% 이하 | 저속 | 구조물 보호 |
| 야간 & 내부온도 적정 | 닫힘 | 정지 | 보온 우선 |

### 3.2 관수/양액 제어 (Irrigation & Nutrient)

| 항목 | 설명 |
|------|------|
| **제어 대상** | 급수 밸브 (ON/OFF + 유량), 양액 배합비 (N-P-K) |
| **주요 판단 요소** | 토양수분, 증발산량(온도+습도+조도), 강수 예보, 작물 생육 단계 |
| **긴급 규칙** | 토양수분 < 30% → 즉시 관수 (기본량 x 1.5) |
| **일반 판단** | 강수 예보 반영, 생육 단계별 양액 비율 조정 |

#### 작물 생육 단계별 양액 배합 가이드

| 생육 단계 | N (질소) | P (인) | K (칼륨) | EC (mS/cm) | 비고 |
|-----------|---------|--------|---------|------------|------|
| 육묘기 | 1.0 | 1.0 | 1.0 | 1.0~1.5 | 균형 성장 |
| 영양생장기 | 1.5 | 0.8 | 1.0 | 1.5~2.0 | 질소 강화 |
| 개화기 | 1.0 | 1.2 | 1.5 | 2.0~2.5 | 인/칼륨 강화 |
| 착과/비대기 | 0.8 | 0.8 | 2.0 | 2.5~3.0 | 칼륨 집중 |
| 수확기 | 0.5 | 0.5 | 1.5 | 2.0~2.5 | 양액 감소 |

#### 관수 판단 로직

```
1. 토양수분 체크
   - < 30%: 긴급 관수 (기본량 x 1.5)
   - 30~50%: 관수 필요 (기본량)
   - 50~70%: 조건부 (증발산량 고려)
   - > 70%: 관수 불필요

2. 기상 보정
   - 3시간 내 강수확률 > 60%: 관수량 50% 감소
   - 맑음 + 고온(>30C): 관수량 20% 증가
   - 강수 직후: 관수 보류 (토양수분 안정 대기)

3. 시간대 보정
   - 최적 관수 시간: 06:00~08:00, 16:00~18:00
   - 한낮(11:00~14:00): 긴급 외 관수 회피 (증발 손실)
```

### 3.3 조명 제어 (Lighting)

| 항목 | 설명 |
|------|------|
| **제어 대상** | 보광등 ON/OFF, 밝기 (0~100%) |
| **주요 판단 요소** | 자연광 조도, 일조시간, 작물 요구 광량, 일출/일몰 |
| **긴급 규칙** | 없음 (생명 위협 아님) |
| **일반 판단** | 일조시간 부족 시 보광, 흐린 날 낮 보광 |

#### 조명 판단 매트릭스

| 조건 | 조명 | 밝기 | 비고 |
|------|------|------|------|
| 일조량 부족 (흐림/비, 연속 2일+) | ON | 60~80% | 보광 필요 |
| 일출 전/일몰 후 + 일조시간 부족 | ON | 40~60% | 연장 보광 |
| 자연광 충분 (맑음, 조도 > 30,000 lux) | OFF | 0% | 전기 절약 |
| 야간 (22:00~04:00) | OFF | 0% | 암기 유지 (작물 호흡) |
| 육묘기 + 조도 < 10,000 lux | ON | 80~100% | 도장 방지 |

### 3.4 차광/보온 제어 (Shading & Insulation)

| 항목 | 설명 |
|------|------|
| **제어 대상** | 차광막 (0~100%), 보온커튼 (0~100%) |
| **주요 판단 요소** | 조도, 내부온도, 외부온도, 야간기온 예보 |
| **긴급 규칙** | 야간 외부온도 < 5C → 보온커튼 100% |
| **일반 판단** | 한낮 고온 시 차광, 야간/새벽 보온 |

#### 차광/보온 판단 매트릭스

| 조건 | 차광막 | 보온커튼 | 비고 |
|------|--------|----------|------|
| 한낮 + 조도 > 70,000 lux + 내부 > 30C | 50~70% | 0% | 과도한 일사 차단 |
| 한낮 + 조도 > 50,000 lux | 30~50% | 0% | 엽소 방지 |
| 맑은 날 일몰 직전 | 0% → 서서히 | 0% → 서서히 | 야간 전환 준비 |
| 야간 + 외부온도 < 10C | 0% | 70~100% | 보온 필수 |
| 야간 + 외부온도 < 5C | 0% | 100% | 동해 방지 |
| 일출 후 | 0% | 서서히 개방 | 급격한 온도변화 방지 |

---

## 4. 기상청 API 연동

### 4.1 사용 API

| API | 용도 | 호출 주기 | 비고 |
|-----|------|----------|------|
| **초단기실황** (getUltraSrtNcst) | 현재 기온, 습도, 풍속, 강수 | 10분 | 실시간 외부환경 |
| **초단기예보** (getUltraSrtFcst) | 6시간 이내 예보 | 30분 | 단기 제어 판단 |
| **단기예보** (getVilageFcst) | 3일 이내 예보 | 3시간 | 중기 계획 수립 |

### 4.2 기상 데이터 모델

```python
@dataclass
class WeatherData:
    # 실황
    temperature: float        # 기온 (C)
    humidity: int             # 습도 (%)
    wind_speed: float         # 풍속 (m/s)
    wind_direction: int       # 풍향 (deg)
    precipitation: float      # 1시간 강수량 (mm)
    precipitation_type: str   # 없음/비/비+눈/눈/소나기
    
    # 예보 (시간대별 리스트)
    forecast_3h: ForecastSlot   # 3시간 후 예보
    forecast_6h: ForecastSlot   # 6시간 후 예보
    forecast_12h: ForecastSlot  # 12시간 후 예보

@dataclass
class ForecastSlot:
    temperature: float
    humidity: int
    precipitation_prob: int   # 강수 확률 (%)
    precipitation_amount: float
    sky_condition: str        # 맑음/구름많음/흐림
    wind_speed: float
```

### 4.3 격자 좌표 변환

기상청 API는 격자 좌표(nx, ny)를 사용하므로 위경도 → 격자 변환 필요:

```python
# 설정 예시 (경북 상주 기준)
FARM_LOCATION = {
    "name": "FarmOS 시험농장",
    "lat": 36.4108,
    "lon": 128.1590,
    "nx": 84,    # 기상청 격자 X
    "ny": 106    # 기상청 격자 Y
}
```

---

## 5. 기술 스택

### 5.1 백엔드 (AI Agent Engine)

| 구분 | 기술 | 용도 |
|------|------|------|
| **Agent 프레임워크** | FastAPI + APScheduler | 주기적 판단 실행 (30초~5분) |
| **LLM** | OpenRouter API (Gemma 4 27B) | 종합 판단 + 자연어 근거 생성 |
| **규칙 엔진** | Python (if/else + 임계값) | 긴급 상황 즉시 대응 |
| **기상 API 클라이언트** | httpx + 캐싱(10분 TTL) | 기상청 초단기/단기 예보 |
| **데이터 저장** | 기존 In-memory + PostgreSQL 확장 | 제어 이력, 판단 로그 |

### 5.2 프론트엔드 (대시보드 확장)

| 구분 | 기술 | 용도 |
|------|------|------|
| **AI 판단 카드** | React + Recharts | 현재 AI 판단 상태 표시 |
| **제어 이력** | 무한 스크롤 테이블 | 과거 제어 명령 히스토리 |
| **수동 오버라이드** | 슬라이더/토글 UI | 사용자가 AI 판단 덮어쓰기 |
| **기상 연동** | 기존 WeatherPage 확장 | 실시간 기상 → AI 판단 연계 표시 |

---

## 6. 데이터 모델 (PostgreSQL 확장)

### 6.1 AI 제어 명령 테이블

```sql
-- AI Agent 제어 명령 이력
CREATE TABLE ai_control_commands (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- 판단 입력
    sensor_snapshot JSONB NOT NULL,       -- 판단 시점 센서값
    weather_snapshot JSONB,               -- 판단 시점 기상 데이터
    
    -- 판단 결과
    control_type TEXT NOT NULL,           -- ventilation, irrigation, lighting, shading
    action JSONB NOT NULL,                -- 제어 명령 상세
    reason TEXT NOT NULL,                 -- AI 판단 근거 (자연어)
    priority TEXT DEFAULT 'normal',       -- emergency, high, medium, low
    decision_source TEXT DEFAULT 'ai',    -- ai, rule, manual
    
    -- 실행 상태
    status TEXT DEFAULT 'pending',        -- pending, executing, completed, overridden, failed
    executed_at TIMESTAMP,
    completed_at TIMESTAMP,
    duration_minutes INTEGER,
    
    -- 수동 오버라이드
    overridden_by TEXT,                   -- 수동 개입한 사용자
    override_reason TEXT
);

-- 작물 프로필
CREATE TABLE crop_profiles (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,                   -- 토마토, 딸기, 상추 등
    growth_stage TEXT,                    -- 육묘기, 영양생장기, 개화기 등
    optimal_temp_min FLOAT,
    optimal_temp_max FLOAT,
    optimal_humidity_min FLOAT,
    optimal_humidity_max FLOAT,
    optimal_light_hours FLOAT,
    nutrient_n FLOAT DEFAULT 1.0,
    nutrient_p FLOAT DEFAULT 1.0,
    nutrient_k FLOAT DEFAULT 1.0,
    ec_min FLOAT,
    ec_max FLOAT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 현재 제어 상태 (최신 1건 유지)
CREATE TABLE control_state (
    id SERIAL PRIMARY KEY,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- 환기
    window_open_pct INTEGER DEFAULT 0,     -- 0~100
    fan_speed INTEGER DEFAULT 0,           -- RPM (0~3000)
    
    -- 관수
    irrigation_valve BOOLEAN DEFAULT FALSE,
    daily_water_total_L FLOAT DEFAULT 0,
    last_watered_at TIMESTAMP,
    nutrient_n FLOAT DEFAULT 1.0,
    nutrient_p FLOAT DEFAULT 1.0,
    nutrient_k FLOAT DEFAULT 1.0,
    
    -- 조명
    lighting_on BOOLEAN DEFAULT FALSE,
    lighting_brightness_pct INTEGER DEFAULT 0,
    
    -- 차광/보온
    shade_pct INTEGER DEFAULT 0,
    insulation_pct INTEGER DEFAULT 0
);
```

### 6.2 기상 캐시 테이블

```sql
CREATE TABLE weather_cache (
    id SERIAL PRIMARY KEY,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    data_type TEXT NOT NULL,               -- ultra_srt_ncst, ultra_srt_fcst, vilag_fcst
    grid_x INTEGER NOT NULL,
    grid_y INTEGER NOT NULL,
    raw_data JSONB NOT NULL,
    parsed_data JSONB NOT NULL,
    expires_at TIMESTAMP NOT NULL
);
```

---

## 7. API 엔드포인트 설계

### 7.1 AI Agent API (Backend 확장)

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/v1/ai-agent/status` | AI Agent 현재 상태 + 최신 판단 |
| GET | `/api/v1/ai-agent/decisions` | 제어 판단 이력 (페이지네이션) |
| GET | `/api/v1/ai-agent/decisions/{id}` | 특정 판단 상세 (센서+기상 스냅샷 포함) |
| POST | `/api/v1/ai-agent/override` | 수동 오버라이드 (특정 제어 항목) |
| GET | `/api/v1/ai-agent/control-state` | 현재 전체 제어 상태 |
| PUT | `/api/v1/ai-agent/crop-profile` | 작물 프로필 수정 |
| POST | `/api/v1/ai-agent/toggle` | AI Agent ON/OFF |

### 7.2 기상 API (신규)

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/v1/weather/current` | 현재 기상 실황 (캐싱) |
| GET | `/api/v1/weather/forecast` | 시간대별 예보 |

---

## 8. 폴더 구조 (확장)

```
backend/app/
├── api/
│   ├── sensors.py              # [기존] 센서 엔드포인트
│   ├── irrigation.py           # [기존] 관수 엔드포인트
│   ├── ai_agent.py             # [신규] AI Agent API
│   └── weather.py              # [신규] 기상 API
├── core/
│   ├── store.py                # [기존] 센서 데이터 저장
│   ├── ai_agent_engine.py      # [신규] AI Agent 엔진 (스케줄러 + 판단 로직)
│   ├── ai_agent_rules.py       # [신규] 규칙 기반 판단 (긴급 대응)
│   ├── ai_agent_llm.py         # [신규] LLM 기반 종합 판단
│   ├── weather_client.py       # [신규] 기상청 API 클라이언트
│   └── weather_cache.py        # [신규] 기상 데이터 캐싱
├── models/
│   ├── ai_control.py           # [신규] 제어 명령 모델
│   ├── crop_profile.py         # [신규] 작물 프로필 모델
│   └── weather.py              # [신규] 기상 데이터 모델
├── schemas/
│   ├── ai_agent.py             # [신규] AI Agent 스키마
│   └── weather.py              # [신규] 기상 스키마
└── prompts/
    └── ai_agent_prompt.py      # [신규] LLM 프롬프트 템플릿

frontend/src/modules/iot/
├── IoTDashboardPage.tsx        # [기존] 센서 대시보드
├── AIAgentPanel.tsx            # [신규] AI Agent 상태 패널
├── AIControlHistory.tsx        # [신규] 제어 이력 테이블
├── ManualOverrideModal.tsx     # [신규] 수동 오버라이드 UI
└── CropProfileSettings.tsx     # [신규] 작물 프로필 설정
```

---

## 9. 구현 순서

### Phase 1: 기상 API 연동 (1~2일)
1. [ ] 기상청 API 클라이언트 구현 (`weather_client.py`)
2. [ ] 위경도 → 격자좌표 변환 유틸리티
3. [ ] 기상 데이터 캐싱 (10분 TTL)
4. [ ] 기상 API 엔드포인트 (`/api/v1/weather/*`)
5. [ ] 기존 WeatherPage mock 데이터 → 실제 API 전환

### Phase 2: 규칙 기반 제어 엔진 (2~3일)
6. [ ] 제어 상태 데이터 모델 (PostgreSQL 테이블)
7. [ ] 작물 프로필 CRUD
8. [ ] 긴급 규칙 엔진 구현 (`ai_agent_rules.py`)
9. [ ] APScheduler 기반 주기적 실행 (30초 간격)
10. [ ] 제어 명령 로깅 + 이력 저장

### Phase 3: LLM 기반 종합 판단 (2~3일)
11. [ ] AI Agent 프롬프트 설계 + 템플릿
12. [ ] OpenRouter LLM 연동 (기존 `journal_parser.py` 패턴 활용)
13. [ ] 센서 + 기상 + 작물 프로필 → LLM 컨텍스트 조합
14. [ ] LLM 응답 파싱 + 제어 명령 변환
15. [ ] 규칙 엔진 + LLM 판단 통합 (규칙 우선, LLM 보완)

### Phase 4: 프론트엔드 대시보드 (2~3일)
16. [ ] AI Agent 상태 패널 컴포넌트
17. [ ] 4대 제어 항목 실시간 표시 (게이지/슬라이더)
18. [ ] AI 판단 근거 카드 (자연어 설명)
19. [ ] 제어 이력 무한 스크롤 테이블
20. [ ] 수동 오버라이드 모달
21. [ ] 작물 프로필 설정 페이지

### Phase 5: 고도화 (선택)
22. [ ] 일일 리포트 자동 생성 (하루 제어 요약)
23. [ ] 이상 패턴 감지 (센서값 급변 시 별도 알림)
24. [ ] 제어 효과 분석 (제어 전후 센서값 비교)
25. [ ] 시즌/월별 최적 파라미터 학습 (히스토리 기반)

---

## 10. 주요 고려사항

### 10.1 가상 제어 (시뮬레이션)

현재 실제 제어 하드웨어(모터, 밸브, 조명)가 없으므로 **모든 제어는 가상으로 실행**된다:
- 제어 명령은 DB에 기록만 하고 실제 하드웨어 신호를 보내지 않음
- 대시보드에서 "가상 제어" 뱃지로 명시 표시
- 향후 ESP8266/릴레이 모듈 추가 시 실제 제어로 전환 가능하도록 인터페이스 분리

### 10.2 LLM 비용 관리

| 항목 | 전략 |
|------|------|
| **호출 빈도** | 정상 상태: 5분 간격 / 변화 감지: 30초 간격 |
| **캐싱** | 동일 조건 반복 시 이전 판단 재사용 (5분 TTL) |
| **규칙 우선** | 명확한 긴급 상황은 LLM 없이 규칙으로 처리 |
| **토큰 절약** | 프롬프트 최소화, JSON 형태 응답 강제 |

### 10.3 조도센서 불안정 대응 (KY-018 LDR)

**현재 상황**: 조도센서(KY-018)가 간헐적으로 값이 0으로 떨어지는 현상 발생. 완전 고장은 아니나 신뢰도가 낮은 상태.

이 문제는 조명 제어와 차광 제어에 직접적인 영향을 주므로, AI Agent 설계 시 반드시 고려해야 한다.

#### 영향 범위

| 제어 항목 | 조도 의존도 | 영향 |
|-----------|:----------:|------|
| **조명 제어** | 높음 | 조도 0 오인 시 불필요한 보광등 가동 → 전력 낭비 |
| **차광 제어** | 높음 | 조도 0 오인 시 차광막 해제 → 실제 강한 햇빛에 작물 엽소 |
| **환기 제어** | 낮음 | 조도가 보조 판단 요소이므로 영향 제한적 |
| **관수 제어** | 낮음 | 증발산량 추정에만 간접 사용 |

#### 대응 전략

**1) 이상값 필터링 (센서 전처리)**
```
- 직전 5회 이동평균 대비 급격한 변화(±80% 이상) → 이상값으로 판정
- 조도 0이 연속 3회 미만이면 → 이전 유효값으로 대체
- 조도 0이 연속 3회 이상이면 → 실제 야간 or 센서 장애로 구분 (시간대 기반)
```

**2) 기상 데이터 교차 검증**
```
- 기상청 "맑음" + 낮시간인데 조도 0 → 센서 이상으로 판정
- 기상청 "흐림/비" + 낮시간 + 조도 0 → 실제 저조도 가능성 인정 (단, 0은 여전히 의심)
- 야간 + 조도 0 → 정상
```

**3) 센서 신뢰도 플래그**
```python
class SensorReliability:
    RELIABLE = "reliable"          # 정상 범위 내
    SUSPICIOUS = "suspicious"      # 이상값 의심 (필터링 적용)
    UNRELIABLE = "unreliable"      # 센서 장애 판정 (기상 데이터로 대체)
```
- AI Agent에 센서 신뢰도 정보를 함께 전달하여, LLM이 판단 시 가중치를 조절
- 대시보드에 조도센서 신뢰도 상태 표시 (정상/의심/장애)

**4) 폴백: 기상 데이터 기반 조도 추정**
```
조도센서 장애 시 → 기상청 하늘상태(맑음/구름/흐림) + 시간대로 조도 추정:
- 맑음 + 정오: ~80,000 lux
- 맑음 + 아침/저녁: ~30,000 lux  
- 구름많음: 추정값 × 0.5
- 흐림: 추정값 × 0.3
- 비: 추정값 × 0.15
```

> **계획팀 검토 요청**: 조도센서 불안정 상태에서 조명/차광 제어의 오판단 리스크가 있습니다. 위 4단계 대응 전략이 충분한지, 또는 조도센서 교체/추가가 선행되어야 하는지 검토 부탁드립니다.

### 10.4 기상청 API 제한

| 제한 | 대응 |
|------|------|
| 일 10,000건 호출 제한 (일반 인증키) | 10분 간격 캐싱 → 일 ~144건 사용 |
| 응답 지연 (1~3초) | 비동기 요청 + 캐시 우선 |
| API 장애 시 | 마지막 캐시 데이터 사용 + 알림 |

---

## 11. Risks and Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| LLM 판단 오류 (과도한 제어) | High | 규칙 기반 상한/하한 제한, 수동 오버라이드 |
| 기상청 API 장애 | Medium | 캐시 데이터 폴백, 센서 데이터만으로 규칙 판단 |
| OpenRouter API 비용 초과 | Medium | 호출 빈도 동적 조절, 규칙 우선 처리 |
| 센서 데이터 이상값 | Medium | 이동평균 + 범위 검증으로 이상값 필터링 |
| **조도센서 불안정 (0값 간헐 발생)** | **High** | **이상값 필터 + 기상 교차검증 + 센서 신뢰도 플래그 + 기상 기반 조도 추정 폴백 (10.3절 참고)** |
| 작물별 최적 조건 부정확 | Low | 프로필 수동 조정 기능 + 점진적 데이터 축적 |

---

## Version History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 0.1 | 2026-04-07 | Initial draft | clover0309 |
