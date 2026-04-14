"""기상청 API 클라이언트 — 실제 API 또는 mock 데이터 제공."""

import math
import random
from datetime import datetime, timezone, timedelta

import httpx

from app.config import settings

_cache: dict = {}
_cache_expiry: datetime | None = None
CACHE_TTL = timedelta(minutes=10)
KST = timezone(timedelta(hours=9))


def _get_base_datetime() -> tuple[str, str]:
    now = datetime.now(KST)
    if now.minute < 40:
        now -= timedelta(hours=1)
    return now.strftime("%Y%m%d"), now.strftime("%H00")


async def _fetch_kma_ultra_srt_ncst() -> dict | None:
    if not settings.KMA_DECODING_KEY:
        return None

    base_date, base_time = _get_base_datetime()
    url = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst"
    params = {
        "serviceKey": settings.KMA_DECODING_KEY,
        "numOfRows": 10, "pageNo": 1, "dataType": "JSON",
        "base_date": base_date, "base_time": base_time,
        "nx": settings.FARM_NX, "ny": settings.FARM_NY,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            items = resp.json().get("response", {}).get("body", {}).get("items", {}).get("item", [])
            if not items:
                return None
            result = {}
            for item in items:
                cat, val = item["category"], item["obsrValue"]
                if cat == "T1H": result["temperature"] = float(val)
                elif cat == "REH": result["humidity"] = int(float(val))
                elif cat == "WSD": result["wind_speed"] = float(val)
                elif cat == "VEC": result["wind_direction"] = int(float(val))
                elif cat == "RN1": result["precipitation"] = float(val)
                elif cat == "PTY":
                    pty_map = {"0": "없음", "1": "비", "2": "비/눈", "3": "눈", "5": "빗방울", "6": "진눈깨비", "7": "눈날림"}
                    result["precipitation_type"] = pty_map.get(val, "없음")
            return result
    except Exception:
        return None


def _generate_mock_weather(sensor_data: dict | None = None) -> dict:
    now = datetime.now(KST)
    kst_hour = now.hour

    if sensor_data:
        base_temp = sensor_data.get("temperature", 22) - random.uniform(1, 4)
        base_humidity = max(30, sensor_data.get("humidity", 60) - random.uniform(5, 15))
    else:
        base_temp = 18 + random.uniform(-3, 5)
        base_humidity = 55 + random.uniform(-10, 15)

    current = {
        "temperature": round(base_temp, 1),
        "humidity": int(base_humidity),
        "wind_speed": round(random.uniform(1.0, 6.0), 1),
        "wind_direction": random.randint(0, 360),
        "precipitation": 0.0,
        "precipitation_type": "없음",
    }

    forecasts = []
    for hours_ahead in [3, 6, 12]:
        future_hour = (kst_hour + hours_ahead) % 24
        temp_shift = -2 if future_hour < 6 or future_hour > 20 else 2
        forecasts.append({
            "hours_ahead": hours_ahead,
            "temperature": round(base_temp + temp_shift + random.uniform(-1, 1), 1),
            "humidity": int(min(95, max(30, base_humidity + random.uniform(-10, 10)))),
            "wind_speed": round(random.uniform(1.0, 6.0), 1),
            "sky": random.choice(["맑음", "구름많음", "흐림"]),
            "precipitation_prob": random.choice([0, 0, 0, 10, 20, 30]),
            "precipitation": 0.0,
        })

    return {"current": current, "forecasts": forecasts, "source": "mock"}


async def get_weather(sensor_data: dict | None = None) -> dict:
    global _cache, _cache_expiry

    now = datetime.now(timezone.utc)
    if _cache_expiry and now < _cache_expiry and _cache:
        return _cache

    if settings.KMA_DECODING_KEY:
        current = await _fetch_kma_ultra_srt_ncst()
        if current:
            # KMA 실황 API는 예보를 포함하지 않으므로 mock 예보로 보충
            mock = _generate_mock_weather(sensor_data)
            result = {"current": current, "forecasts": mock["forecasts"], "source": {"current": "kma", "forecasts": "mock"}}
            _cache = result
            _cache_expiry = now + CACHE_TTL
            return result

    result = _generate_mock_weather(sensor_data)
    _cache = result
    _cache_expiry = now + CACHE_TTL
    return result
