"""해충 이미지 분류 서비스 — RunPod 에 배포된 pest-detector-deploy 서버 호출.

서버 측 엔드포인트 (deploy/server.py):
    POST /classify      multipart file=...
응답: {"pred": "<한국어 클래스>", "raw": "<원본>", "elapsed_s": float}

PEST_CLASSIFIER_URL 미설정 시 ConfigurationError, 호출 실패 시 ClassifierError.
"""
import logging
from typing import Optional

import httpx

from app.core.config import settings


logger = logging.getLogger(__name__)


class ClassifierError(Exception):
    """분류 서버 호출 실패 (네트워크·타임아웃·HTTP 에러)."""


class ConfigurationError(Exception):
    """PEST_CLASSIFIER_URL 미설정."""


async def classify_pest_image(
    image_bytes: bytes,
    filename: str = "image.jpg",
    content_type: str = "image/jpeg",
) -> dict:
    """이미지 바이트를 분류 서버로 전송하고 예측 결과를 돌려준다.

    반환값: {"pred": str, "raw": str, "elapsed_s": float}
    """
    base_url = (settings.PEST_CLASSIFIER_URL or "").rstrip("/")
    if not base_url:
        raise ConfigurationError("PEST_CLASSIFIER_URL 이 설정되지 않았습니다.")

    timeout = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)
    async with httpx.AsyncClient(http1=True, http2=False, timeout=timeout) as client:
        try:
            resp = await client.post(
                f"{base_url}/classify",
                files={"file": (filename, image_bytes, content_type)},
            )
        except httpx.HTTPError as e:
            logger.exception("분류 서버 호출 실패: %s", base_url)
            raise ClassifierError(f"분류 서버 통신 오류: {e}") from e

    if resp.status_code != 200:
        body = resp.text[:200]
        logger.error("분류 서버 비정상 응답 %s: %s", resp.status_code, body)
        raise ClassifierError(f"분류 서버 오류 ({resp.status_code}): {body}")

    try:
        data = resp.json()
    except ValueError as e:
        raise ClassifierError(f"분류 서버 응답 파싱 실패: {e}") from e

    if "pred" not in data:
        raise ClassifierError(f"예상치 못한 응답 형식: {data}")
    return data


async def classifier_health() -> Optional[dict]:
    """분류 서버 헬스 체크. URL 미설정이면 None."""
    base_url = (settings.PEST_CLASSIFIER_URL or "").rstrip("/")
    if not base_url:
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base_url}/health")
            return resp.json() if resp.status_code == 200 else None
    except httpx.HTTPError:
        return None
