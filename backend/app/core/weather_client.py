"""기상청 API 클라이언트 — 실제 API 또는 mock 데이터 제공."""

import math
import random
from datetime import datetime, timezone, timedelta

import httpx

from app.core.config import settings

# 캐시 (10분 TTL)
_cache: dict = {}
_cache_expiry: datetime | None = None
CACHE_TTL = timedelta(minutes=10)

KST = timezone(timedelta(hours=9))


def _latlon_to_grid(lat: float, lon: float) -> tuple[int, int]:
    """위경도 → 기상청 격자좌표 변환 (Lambert Conformal Conic)."""
    RE = 6371.00877
    GRID = 5.0
    SLAT1 = 30.0
    SLAT2 = 60.0
    OLON = 126.0
    OLAT = 38.0
    XO = 43
    YO = 136

    DEGRAD = math.pi / 180.0
    re = RE / GRID
    slat1 = SLAT1 * DEGRAD
    slat2 = SLAT2 * DEGRAD
    olon = OLON * DEGRAD
    olat = OLAT * DEGRAD

    sn = math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5)
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(sn)
    sf = math.tan(math.pi * 0.25 + slat1 * 0.5)
    sf = (sf ** sn) * math.cos(slat1) / sn
    ro = math.tan(math.pi * 0.25 + olat * 0.5)
    ro = re * sf / (ro ** sn)

    ra = math.tan(math.pi * 0.25 + lat * DEGRAD * 0.5)
    ra = re * sf / (ra ** sn)
    theta = lon * DEGRAD - olon
    if theta > math.pi:
        theta -= 2.0 * math.pi
    if theta < -math.pi:
        theta += 2.0 * math.pi
    theta *= sn

    x = int(ra * math.sin(theta) + XO + 0.5)
    y = int(ro - ra * math.cos(theta) + YO + 0.5)
    return x, y


def _get_base_datetime() -> tuple[str, str]:
    """초단기실황 API 기준시각 산출 (정시 기준, 40분 이후 가능)."""
    now = datetime.now(KST)
    if now.minute < 40:
        now -= timedelta(hours=1)
    return now.strftime("%Y%m%d"), now.strftime("%H00")


async def _fetch_kma_ultra_srt_ncst() -> dict | None:
    """기상청 초단기실황 API 호출."""
    if not settings.KMA_DECODING_KEY:
        return None

    base_date, base_time = _get_base_datetime()
    url = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst"
    params = {
        "serviceKey": settings.KMA_DECODING_KEY,
        "numOfRows": 10,
        "pageNo": 1,
        "dataType": "JSON",
        "base_date": base_date,
        "base_time": base_time,
        "nx": settings.FARM_NX,
        "ny": settings.FARM_NY,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("response", {}).get("body", {}).get("items", {}).get("item", [])
            if not items:
                return None

            result = {}
            for item in items:
                cat = item["category"]
                val = item["obsrValue"]
                if cat == "T1H":
                    result["temperature"] = float(val)
                elif cat == "REH":
                    result["humidity"] = int(float(val))
                elif cat == "WSD":
                    result["wind_speed"] = float(val)
                elif cat == "VEC":
                    result["wind_direction"] = int(float(val))
                elif cat == "RN1":
                    result["precipitation"] = float(val)
                elif cat == "PTY":
                    pty_map = {"0": "없음", "1": "비", "2": "비/눈", "3": "눈", "5": "빗방울", "6": "진눈깨비", "7": "눈날림"}
                    result["precipitation_type"] = pty_map.get(val, "없음")

            return result
    except Exception:
        return None


async def _fetch_kma_ultra_srt_fcst() -> list[dict] | None:
    """기상청 초단기예보 API 호출."""
    if not settings.KMA_DECODING_KEY:
        return None

    base_date, base_time = _get_base_datetime()
    url = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtFcst"
    params = {
        "serviceKey": settings.KMA_DECODING_KEY,
        "numOfRows": 60,
        "pageNo": 1,
        "dataType": "JSON",
        "base_date": base_date,
        "base_time": base_time,
        "nx": settings.FARM_NX,
        "ny": settings.FARM_NY,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("response", {}).get("body", {}).get("items", {}).get("item", [])
            if not items:
                return None

            # 시간대별로 그룹핑
            forecasts: dict[str, dict] = {}
            for item in items:
                key = f"{item['fcstDate']}_{item['fcstTime']}"
                if key not in forecasts:
                    forecasts[key] = {"date": item["fcstDate"], "time": item["fcstTime"]}
                cat = item["category"]
                val = item["fcstValue"]
                if cat == "T1H":
                    forecasts[key]["temperature"] = float(val)
                elif cat == "REH":
                    forecasts[key]["humidity"] = int(float(val))
                elif cat == "WSD":
                    forecasts[key]["wind_speed"] = float(val)
                elif cat == "SKY":
                    sky_map = {"1": "맑음", "3": "구름많음", "4": "흐림"}
                    forecasts[key]["sky"] = sky_map.get(val, "맑음")
                elif cat == "RN1":
                    forecasts[key]["precipitation"] = float(val) if val != "강수없음" else 0.0

            return list(forecasts.values())
    except Exception:
        return None


def _generate_mock_weather(sensor_data: dict | None = None) -> dict:
    """센서 데이터 기반 mock 기상 데이터 생성."""
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

    # 시간대별 예보 생성 (3, 6, 12시간 후)
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
    """기상 데이터를 반환한다. KMA API 키가 있으면 실제 호출, 없으면 mock.

    Returns:
        {
            "current": { temperature, humidity, wind_speed, ... },
            "forecasts": [ { hours_ahead, temperature, ... }, ... ],
            "source": "kma" | "mock"
        }
    """
    global _cache, _cache_expiry

    # 캐시 확인
    now = datetime.now(timezone.utc)
    if _cache_expiry and now < _cache_expiry and _cache:
        return _cache

    # KMA API 시도
    if settings.KMA_DECODING_KEY:
        current = await _fetch_kma_ultra_srt_ncst()
        forecast_items = await _fetch_kma_ultra_srt_fcst()

        if current:
            forecasts = []
            if forecast_items:
                for i, item in enumerate(forecast_items[:3]):
                    forecasts.append({
                        "hours_ahead": (i + 1) * 3,
                        "temperature": item.get("temperature", current["temperature"]),
                        "humidity": item.get("humidity", current["humidity"]),
                        "wind_speed": item.get("wind_speed", current.get("wind_speed", 2.0)),
                        "sky": item.get("sky", "맑음"),
                        "precipitation_prob": 0,
                        "precipitation": item.get("precipitation", 0.0),
                    })

            result = {"current": current, "forecasts": forecasts, "source": "kma"}
            _cache = result
            _cache_expiry = now + CACHE_TTL
            return result

    # Mock 폴백
    result = _generate_mock_weather(sensor_data)
    _cache = result
    _cache_expiry = now + CACHE_TTL
    return result
