# IoT 중계 서버 구축 계획 (N100 서버)

## 1. 배경 및 목적

ESP8266에서 센서 데이터를 수집하여 FarmOS 프론트엔드에 전달해야 한다.
로컬 PC 직접 통신은 네트워크 환경에 따라 불안정하고,
ngrok은 HTTPS만 지원하여 ESP8266의 TLS 메모리 한계로 연결이 실패한다.

**해결책**: 개인 N100 서버에 경량 중계 FastAPI 앱을 Docker로 배포.
ESP8266은 핫스팟을 통해 N100 서버에 HTTP로 직접 통신한다.

---

## 2. 전체 아키텍처

```
┌──────────────┐        HTTP POST         ┌──────────────────┐
│   ESP8266    │ ───────────────────────→  │   N100 서버       │
│  (핫스팟)     │     :9000/api/v1/sensors  │   Docker          │
│  DHT11+CdS   │                          │                   │
└──────────────┘                          │  ┌──────────────┐ │
                                          │  │ iot-relay    │ │
                                          │  │ FastAPI      │ │
                                          │  │ :9000        │ │
                                          │  └──────┬───────┘ │
                                          │         │         │
                                          │  nginx (80/443)   │
                                          │  (포트폴리오 배포중)│
                                          └──────────────────┘
                                                    │
                                          GET /api/v1/sensors/*
                                                    │
                                          ┌──────────────────┐
                                          │   프론트엔드      │
                                          │   (개발 PC)       │
                                          │   localhost:5173  │
                                          └──────────────────┘
```

**포트 배분**:
- 80/443: nginx (포트폴리오 배포 - 기존 유지)
- 9000: IoT 중계 서버 (신규)

---

## 3. 구현 위치

프로젝트 루트의 `iot_relay_server/` 디렉토리:

```
iot_relay_server/
├── app/
│   ├── __init__.py
│   ├── main.py           # FastAPI 앱 (CORS, 라우터)
│   ├── store.py           # 인메모리 센서 데이터 저장소
│   ├── schemas.py         # Pydantic 검증 스키마
│   └── config.py          # 환경변수 설정
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env
```

---

## 4. 주요 엔드포인트

| Method | Path | 인증 | 용도 |
|--------|------|------|------|
| POST | `/api/v1/sensors` | X-API-Key | ESP8266 데이터 수신 |
| GET | `/api/v1/sensors/latest` | 없음 | 최신 센서 값 1건 |
| GET | `/api/v1/sensors/history` | 없음 | 시계열 데이터 (limit 파라미터) |
| GET | `/api/v1/sensors/alerts` | 없음 | 알림 목록 |
| PATCH | `/api/v1/sensors/alerts/{id}/resolve` | 없음 | 알림 해결 처리 |
| POST | `/api/v1/irrigation/trigger` | 없음 | 수동 관개 제어 |
| GET | `/api/v1/irrigation/events` | 없음 | 관개 이벤트 이력 |
| GET | `/health` | 없음 | 헬스체크 |

> GET 엔드포인트는 JWT 인증 없이 공개 (시연용).
> POST /sensors만 API Key로 보호.

---

## 5. 배포 순서

| 단계 | 작업 | 확인 방법 |
|------|------|----------|
| 1 | N100에 `iot_relay_server/` 전체 복사 (scp, git clone 등) | `ls iot_relay_server/` |
| 2 | `cd iot_relay_server && docker compose up -d --build` | `docker ps`에서 iot-relay 확인 |
| 3 | N100 방화벽에서 9000 포트 개방 | `curl http://N100_IP:9000/health` |
| 4 | ESP8266 `.ino`에 N100 공인 IP 설정 후 업로드 | 시리얼 모니터 `Server Say : 201` |
| 5 | 프론트엔드 `useSensorData.ts`의 API_BASE 변경 | IoT 대시보드에 실시간 데이터 표시 |

---

## 6. ESP8266 변경사항

```cpp
// .ino 파일에서 변경
const char* serverHost = "http://{N100_공인IP}:9000";
```

- WiFiClient (HTTP) 사용 — TLS 불필요
- ESP8266은 핫스팟으로 인터넷 연결

---

## 7. 프론트엔드 변경사항

`frontend/src/hooks/useSensorData.ts`:

```typescript
// 변경 전
const API_BASE = 'http://localhost:8000/api/v1';

// 변경 후 (환경변수 분리 권장)
const API_BASE = import.meta.env.VITE_IOT_API_URL || 'http://localhost:8000/api/v1';
```

`.env` 또는 `.env.local`:
```
VITE_IOT_API_URL=http://{N100_공인IP}:9000/api/v1
```

---

## 8. 보안 참고

- POST만 API Key 보호 (무단 데이터 삽입 방지)
- GET은 인증 없이 공개 (시연용)
- 인메모리 저장, 서버 재시작 시 초기화
- CORS `allow_origins=["*"]` (시연 환경)
