"""AI Agent Decision Bridge (Relay → FarmOS Postgres).

Design Ref: §2.3 Data Flow (Failure/Recovery), §7 Bridge 내부 예외 처리, §11 services/ai_agent_bridge.py

Plan SC-1: decision 수신 → ai_agent_decisions insert p95 < 5s
Plan SC-5: FarmOS BE 재시작 후에도 이전 decisions 유지

구현 전략:
- 이중 채널: SSE 실시간 + HTTP backfill(기동/재접속 시)
- 멱등 UPSERT: INSERT ... ON CONFLICT (id) DO NOTHING — SSE/backfill 중복 무해
- Exponential backoff: 1→2→4→8→16→32→60s (cap)
- AI_AGENT_BRIDGE_ENABLED 플래그로 전체 비활성화 가능 (Relay patch 미적용 시 안전)

Lifecycle:
- main.py lifespan 에서 AiAgentBridge 인스턴스 생성 → start() → (앱 종료) stop()
- start/stop 은 비차단 (asyncio.create_task 기반)
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models.ai_agent import AiAgentDecision

logger = logging.getLogger(__name__)

# ── 상수 ──────────────────────────────────────────────────────────────────────

_MIN_BACKOFF = 1.0
_MAX_BACKOFF = 60.0
_SSE_READ_TIMEOUT = 120.0  # SSE keep-alive 여유, Relay 가 주기적 heartbeat 보낸다고 가정
_BACKFILL_MAX_PAGES = 500  # 안전 장치 (page_size 200 * 500 = 10만 건)


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────


def _parse_iso(ts: str) -> datetime:
    """Relay 가 내려주는 ISO8601 문자열을 aware datetime 으로 변환."""
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            return _parse_iso(value)
        except ValueError:
            return None
    return None


# ── 메인 Bridge 클래스 ────────────────────────────────────────────────────────


class AiAgentBridge:
    """Relay SSE + HTTP backfill 로 AI Agent decisions 를 FarmOS Postgres 에 적재.

    단일 asyncio.Task 로 실행되며, 실패 시 exponential backoff 로 재접속한다.
    """

    def __init__(self, settings: Settings, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._client: httpx.AsyncClient | None = None

        # 상태 (GET /ai-agent/bridge/status 등에서 노출 가능)
        self.healthy: bool = False
        self.last_event_at: datetime | None = None
        self.last_backfill_at: datetime | None = None
        self.last_error: str | None = None
        self.total_processed: int = 0

    # ── 공개 API ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """lifespan 에서 호출. 이미 실행 중이면 no-op."""
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name="ai_agent_bridge")
        logger.info(
            "ai_agent_bridge.started base_url=%s", self._settings.IOT_RELAY_BASE_URL
        )

    async def stop(self) -> None:
        """앱 종료 시 호출. 현재 연결 끊고 task 취소."""
        self._stop_event.set()
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:  # noqa: BLE001
                pass
            self._client = None
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._task = None
        self.healthy = False
        logger.info("ai_agent_bridge.stopped processed=%d", self.total_processed)

    # ── 루프 + 재접속 ─────────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        """Backfill + SSE 구독 루프. 실패하면 backoff 후 재시도."""
        backoff = _MIN_BACKOFF
        while not self._stop_event.is_set():
            try:
                await self._backfill_since_last()
                self.healthy = True
                self.last_error = None
                await self._connect_and_stream()
                # 정상 종료(서버가 close) → 즉시 재연결
                backoff = _MIN_BACKOFF
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.healthy = False
                self.last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "ai_agent_bridge.loop_error backoff=%.1fs err=%s",
                    backoff,
                    self.last_error,
                )
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=backoff)
                    break  # stop 신호
                except asyncio.TimeoutError:
                    backoff = min(backoff * 2, _MAX_BACKOFF)

    # ── HTTP Backfill ─────────────────────────────────────────────────────────

    async def _backfill_since_last(self) -> int:
        """FarmOS 의 가장 최근 timestamp 이후 decisions 를 Relay 에서 당겨와 UPSERT."""
        async with self._session_factory() as db:
            last_ts = await db.scalar(select(AiAgentDecision.timestamp).order_by(AiAgentDecision.timestamp.desc()).limit(1))

        client = self._get_client()
        total = 0
        cursor_since = last_ts.isoformat() if last_ts else None

        for _ in range(_BACKFILL_MAX_PAGES):
            params: dict[str, Any] = {"limit": self._settings.AI_AGENT_BACKFILL_PAGE_SIZE}
            if cursor_since:
                params["since"] = cursor_since

            resp = await client.get("/api/v1/ai-agent/decisions", params=params)
            if resp.status_code == 404:
                # Relay patch 미적용 (엔드포인트 없음) — 조용히 종료
                logger.info("ai_agent_bridge.backfill_not_supported (Relay may not be patched yet)")
                return 0
            resp.raise_for_status()

            payload = resp.json()
            items = payload if isinstance(payload, list) else payload.get("items", [])
            if not items:
                break

            max_ts_in_batch: datetime | None = None
            async with self._session_factory() as db:
                for raw in items:
                    applied = await self._upsert_and_summarize(db, raw)
                    if applied:
                        total += 1
                        self.total_processed += 1
                        ts = _coerce_datetime(raw.get("timestamp"))
                        if ts and (max_ts_in_batch is None or ts > max_ts_in_batch):
                            max_ts_in_batch = ts
                await db.commit()

            if len(items) < self._settings.AI_AGENT_BACKFILL_PAGE_SIZE:
                break
            if max_ts_in_batch is None:
                break
            cursor_since = max_ts_in_batch.isoformat()

        self.last_backfill_at = datetime.now(timezone.utc)
        if total > 0:
            logger.info("ai_agent_bridge.backfill_done count=%d", total)
        return total

    # ── SSE 구독 ──────────────────────────────────────────────────────────────

    async def _connect_and_stream(self) -> None:
        """Relay /ai-agent/stream 에 연결해 ai_decision 이벤트를 읽는다."""
        client = self._get_client()
        # Relay 는 ai_decision 이벤트를 공용 /sensors/stream SSE 에 포함 발행한다
        # (기존 프론트 useSensorData 와 동일 스트림 구독, event 필터링으로 분리)
        url = "/api/v1/sensors/stream"

        async with client.stream("GET", url, timeout=_SSE_READ_TIMEOUT) as resp:
            if resp.status_code == 404:
                logger.info("ai_agent_bridge.sse_not_supported (Relay stream unavailable)")
                raise RuntimeError("SSE endpoint not found (404)")
            resp.raise_for_status()

            current_event: str | None = None
            async for line in resp.aiter_lines():
                if self._stop_event.is_set():
                    break
                if not line:
                    current_event = None
                    continue
                if line.startswith(":"):
                    continue  # heartbeat/comment
                if line.startswith("event:"):
                    current_event = line[len("event:"):].strip()
                    continue
                if line.startswith("data:"):
                    data_str = line[len("data:"):].strip()
                    if not data_str:
                        continue
                    # ai_decision 이벤트만 처리 (다른 이벤트는 무시)
                    if current_event and current_event != "ai_decision":
                        continue
                    try:
                        raw = json.loads(data_str)
                    except json.JSONDecodeError:
                        logger.warning("ai_agent_bridge.bad_sse_data: %s", data_str[:200])
                        continue
                    await self._handle_decision(raw)

    async def _handle_decision(self, raw: dict[str, Any]) -> None:
        """SSE 이벤트 1건 처리 — UPSERT + 요약 증분."""
        async with self._session_factory() as db:
            try:
                applied = await self._upsert_and_summarize(db, raw)
                await db.commit()
            except Exception as exc:  # noqa: BLE001
                await db.rollback()
                logger.warning("ai_agent_bridge.upsert_failed id=%s err=%s", raw.get("id"), exc)
                return

        if applied:
            self.total_processed += 1
            self.last_event_at = datetime.now(timezone.utc)

    # ── UPSERT 로직 ──────────────────────────────────────────────────────────

    async def _upsert_and_summarize(self, db: AsyncSession, raw: dict[str, Any]) -> bool:
        """원본 INSERT (멱등) + 신규 행이면 일/시간 요약 bump.

        Returns: True if row was inserted (not a duplicate), False if skipped.
        """
        decision_id = str(raw.get("id") or "").strip()
        timestamp = _coerce_datetime(raw.get("timestamp"))
        control_type = (raw.get("control_type") or "").strip()
        if not decision_id or timestamp is None or not control_type:
            logger.warning("ai_agent_bridge.invalid_payload keys=%s", list(raw.keys()))
            return False

        priority = (raw.get("priority") or "low").strip()
        source = (raw.get("source") or "rule").strip()
        reason = raw.get("reason") or ""
        action = raw.get("action") or {}
        tool_calls = raw.get("tool_calls") or []
        sensor_snapshot = raw.get("sensor_snapshot")
        duration_ms = raw.get("duration_ms")

        # 1) 원본 멱등 INSERT
        insert_sql = text(
            """
            INSERT INTO ai_agent_decisions
                (id, timestamp, control_type, priority, source, reason,
                 action, tool_calls, sensor_snapshot, duration_ms, created_at)
            VALUES
                (:id, :ts, :ct, :pr, :src, :reason,
                 CAST(:action AS jsonb), CAST(:tool_calls AS jsonb),
                 CAST(:sensor_snapshot AS jsonb), :dur, now())
            ON CONFLICT (id) DO NOTHING
            """
        )
        result = await db.execute(
            insert_sql,
            {
                "id": decision_id,
                "ts": timestamp,
                "ct": control_type,
                "pr": priority,
                "src": source,
                "reason": reason,
                "action": json.dumps(action),
                "tool_calls": json.dumps(tool_calls),
                "sensor_snapshot": json.dumps(sensor_snapshot) if sensor_snapshot is not None else None,
                "dur": duration_ms,
            },
        )
        if result.rowcount == 0:
            return False  # 중복

        # 2) 집계 bump — 이미 신규 row 확정
        await self._bump_daily(db, timestamp.date(), control_type, priority, source, timestamp, duration_ms)
        await self._bump_hourly(db, timestamp, control_type, priority, source)
        return True

    async def _bump_daily(
        self,
        db: AsyncSession,
        day: date,
        control_type: str,
        priority: str,
        source: str,
        last_at: datetime,
        duration_ms: int | None,
    ) -> None:
        """일별 집계 UPSERT — count +1, by_source/by_priority 해당 키 +1, avg_duration_ms 가중 평균."""
        sql = text(
            """
            INSERT INTO ai_agent_activity_daily
                (day, control_type, count, by_source, by_priority,
                 avg_duration_ms, last_at, updated_at)
            VALUES
                (:day, :ct, 1,
                 jsonb_build_object(CAST(:src AS text), 1),
                 jsonb_build_object(CAST(:pr AS text), 1),
                 :dur, :last_at, now())
            ON CONFLICT (day, control_type) DO UPDATE SET
                count = ai_agent_activity_daily.count + 1,
                by_source = jsonb_set(
                    ai_agent_activity_daily.by_source,
                    ARRAY[CAST(:src AS text)],
                    to_jsonb(COALESCE((ai_agent_activity_daily.by_source->>:src)::int, 0) + 1)
                ),
                by_priority = jsonb_set(
                    ai_agent_activity_daily.by_priority,
                    ARRAY[CAST(:pr AS text)],
                    to_jsonb(COALESCE((ai_agent_activity_daily.by_priority->>:pr)::int, 0) + 1)
                ),
                avg_duration_ms = CASE
                    WHEN :dur IS NULL THEN ai_agent_activity_daily.avg_duration_ms
                    WHEN ai_agent_activity_daily.avg_duration_ms IS NULL THEN :dur
                    ELSE (
                        (ai_agent_activity_daily.avg_duration_ms * ai_agent_activity_daily.count + :dur)
                        / (ai_agent_activity_daily.count + 1)
                    )
                END,
                last_at = GREATEST(ai_agent_activity_daily.last_at, :last_at),
                updated_at = now()
            """
        )
        await db.execute(
            sql,
            {
                "day": day,
                "ct": control_type,
                "src": source,
                "pr": priority,
                "dur": duration_ms,
                "last_at": last_at,
            },
        )

    async def _bump_hourly(
        self,
        db: AsyncSession,
        ts: datetime,
        control_type: str,
        priority: str,
        source: str,
    ) -> None:
        """시간별 집계 UPSERT (최근 48h 그래프용). hour = date_trunc('hour', ts)."""
        hour_bucket = ts.replace(minute=0, second=0, microsecond=0)
        sql = text(
            """
            INSERT INTO ai_agent_activity_hourly
                (hour, control_type, count, by_source, by_priority, last_at, updated_at)
            VALUES
                (:hour, :ct, 1,
                 jsonb_build_object(CAST(:src AS text), 1),
                 jsonb_build_object(CAST(:pr AS text), 1),
                 :last_at, now())
            ON CONFLICT (hour, control_type) DO UPDATE SET
                count = ai_agent_activity_hourly.count + 1,
                by_source = jsonb_set(
                    ai_agent_activity_hourly.by_source,
                    ARRAY[CAST(:src AS text)],
                    to_jsonb(COALESCE((ai_agent_activity_hourly.by_source->>:src)::int, 0) + 1)
                ),
                by_priority = jsonb_set(
                    ai_agent_activity_hourly.by_priority,
                    ARRAY[CAST(:pr AS text)],
                    to_jsonb(COALESCE((ai_agent_activity_hourly.by_priority->>:pr)::int, 0) + 1)
                ),
                last_at = GREATEST(ai_agent_activity_hourly.last_at, :last_at),
                updated_at = now()
            """
        )
        await db.execute(
            sql,
            {
                "hour": hour_bucket,
                "ct": control_type,
                "src": source,
                "pr": priority,
                "last_at": ts,
            },
        )

    # ── httpx 클라이언트 ─────────────────────────────────────────────────────

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {
                "Accept": "text/event-stream, application/json",
                "X-API-Key": self._settings.IOT_RELAY_API_KEY,
            }
            self._client = httpx.AsyncClient(
                base_url=self._settings.IOT_RELAY_BASE_URL,
                headers=headers,
                timeout=httpx.Timeout(connect=5.0, read=_SSE_READ_TIMEOUT, write=5.0, pool=5.0),
            )
        return self._client
