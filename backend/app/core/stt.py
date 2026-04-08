"""Groq Whisper STT 클라이언트."""

import httpx

from app.core.config import settings


async def transcribe_audio(
    file_bytes: bytes,
    filename: str = "audio.webm",
    content_type: str = "audio/webm",
    language: str = "ko",
) -> str:
    """오디오 바이트를 Groq Whisper로 전사.

    Returns:
        전사된 텍스트 (실패 시 예외 발생).
    """
    if not settings.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY가 설정되지 않았습니다.")

    headers = {"Authorization": f"Bearer {settings.GROQ_API_KEY}"}
    files = {"file": (filename, file_bytes, content_type)}
    data = {
        "model": settings.GROQ_STT_MODEL,
        "language": language,
        "response_format": "json",
        "temperature": "0",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            settings.GROQ_STT_URL, headers=headers, files=files, data=data
        )
        resp.raise_for_status()

    payload = resp.json()
    return (payload.get("text") or "").strip()
