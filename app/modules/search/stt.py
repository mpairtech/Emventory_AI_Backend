

import httpx
from openai import AsyncOpenAI
from app.core.config import settings
from app.core.exceptions import SpeechToTextError, AudioProcessingError
import logging

logger = logging.getLogger(__name__)

# client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
def _get_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

# OpenAI supported audio MIME types
ALLOWED_CONTENT_TYPES = {
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/webm",
    "audio/mp4",
    "audio/ogg",
    "audio/flac",
    "audio/m4a",
    "audio/x-m4a",
}

# Map content-type → file extension (used in the multipart filename)
_CONTENT_TYPE_EXT: dict[str, str] = {
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/webm": "webm",
    "audio/mp4": "mp4",
    "audio/ogg": "ogg",
    "audio/flac": "flac",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
}

MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25 MB — OpenAI hard limit


async def transcribe_from_r2(file_url: str, language: str = "en") -> str:
    """
    Download audio from Cloudflare R2 URL and transcribe
    using gpt-4o-mini-transcribe.

    Args:
        file_url: Presigned or public R2 URL.
        language:  ISO-639-1 language code (e.g. "en", "bn").

    Returns:
        Stripped transcript string.

    Raises:
        AudioProcessingError: Download or validation failure.
        SpeechToTextError:    OpenAI transcription failure.
    """
    # ── 1. Download from R2 ────────────────────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=60.0) as http:
            response = await http.get(file_url)
            response.raise_for_status()
            audio_bytes = response.content
            raw_ct = response.headers.get("content-type", "audio/mpeg")
            content_type = raw_ct.split(";")[0].strip().lower()
    except httpx.HTTPStatusError as e:
        raise AudioProcessingError(
            f"Failed to download audio from R2: HTTP {e.response.status_code}"
        )
    except httpx.TimeoutException:
        raise AudioProcessingError("Timed out downloading audio from R2 (60s limit)")
    except Exception as e:
        raise AudioProcessingError(f"R2 download error: {str(e)}")

    # ── 2. Validate ────────────────────────────────────────────────────────
    if len(audio_bytes) == 0:
        raise AudioProcessingError("Downloaded audio file is empty")

    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise AudioProcessingError(
            f"Audio file exceeds 25MB OpenAI limit "
            f"(got {len(audio_bytes) / 1024 / 1024:.1f} MB)"
        )

    if content_type not in ALLOWED_CONTENT_TYPES:
        logger.warning(
            f"[STT] Unexpected content-type '{content_type}' — proceeding with 'audio/mpeg'"
        )
        content_type = "audio/mpeg"

    ext = _CONTENT_TYPE_EXT.get(content_type, "mp3")
    filename = f"audio.{ext}"

    logger.info(
        f"[STT] Downloaded {len(audio_bytes) / 1024:.1f} KB | "
        f"content-type={content_type} | lang={language}"
    )

    # ── 3. Transcribe ──────────────────────────────────────────────────────
    try:
        transcript = await _get_client().audio.transcriptions.create(  # ← client() call
            model="gpt-4o-mini-transcribe",
            file=(filename, audio_bytes, content_type),
            language=language,
            response_format="text",
        )
        text = transcript.strip() if isinstance(transcript, str) else str(transcript).strip()
        logger.info(f"[STT] Transcribed: '{text[:120]}'")
        return text

    except Exception as e:
        error_msg = str(e).lower()
        if "rate limit" in error_msg or "429" in error_msg:
            raise SpeechToTextError(f"OpenAI STT rate limit exceeded: {str(e)}")
        if "invalid file" in error_msg or "unsupported" in error_msg:
            raise AudioProcessingError(f"OpenAI rejected audio format: {str(e)}")
        raise SpeechToTextError(f"Transcription failed: {str(e)}")