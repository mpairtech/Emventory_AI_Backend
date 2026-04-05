

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.v1.schemas import R2VoiceSearchRequest, RAGResponse, ErrorResponse
from app.core.auth import verify_api_key          # reuse your existing HMAC auth dep
from app.db.session import get_db
from app.modules.search.stt import transcribe_from_r2
from app.modules.search.service import SearchService
from app.core.exceptions import (
    AudioProcessingError,
    SpeechToTextError,
    RateLimitError,
    EmbeddingGenerationError,
    LLMGenerationError,
)
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["Voice Search"])


@router.post(
    "/voice",
    response_model=RAGResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Bad request / invalid audio"},
        413: {"model": ErrorResponse, "description": "Audio file too large"},
        429: {"model": ErrorResponse, "description": "STT or LLM rate limit hit"},
        503: {"model": ErrorResponse, "description": "Upstream AI service unavailable"},
    },
    summary="Voice search via Cloudflare R2",
    description=(
        "Accepts a Cloudflare R2 presigned/public audio URL. "
        "Downloads the file, transcribes it with gpt-4o-mini-transcribe, "
        "then runs the existing RAG search pipeline and returns results."
    ),
)
async def voice_search(
    body: R2VoiceSearchRequest,
    db: Session = Depends(get_db),
    _: None = Depends(verify_api_key),
):
    logger.info(
        f"[VoiceSearch] org={body.org_id} | lang={body.language} | "
        f"top_k={body.top_k} | provider={body.provider}"
    )

    # ── Step 1: Transcribe ──────────────────────────────────────────────────
    try:
        transcript = await transcribe_from_r2(
            file_url=body.file_url,
            language=body.language,
        )
    except AudioProcessingError as e:
        logger.warning(f"[VoiceSearch] Audio error: {e}")
        status_code = (
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
            if "25MB" in str(e)
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=str(e))
    except SpeechToTextError as e:
        logger.warning(f"[VoiceSearch] STT error: {e}")
        if "rate limit" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e)
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)
        )

    if not transcript:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transcription returned empty text. Check audio quality or language code.",
        )

    logger.info(f"[VoiceSearch] Transcript: '{transcript[:120]}'")

    # ── Step 2: RAG Search ──────────────────────────────────────────────────
    provider = (body.provider or "openai").lower()

    try:
        result = SearchService.rag_search(
            db=db,
            query=transcript,
            org_id=body.org_id,
            llm_provider=provider,
            top_k=body.top_k,
            filters=body.filters,
        )
    except RateLimitError as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e)
        )
    except (EmbeddingGenerationError, LLMGenerationError) as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)
        )
    except Exception as e:
        logger.error(f"[VoiceSearch] Unexpected RAG error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Search pipeline failed unexpectedly.",
        )

    # ── Step 3: Return ──────────────────────────────────────────────────────
    return {
        "answer": result.get("answer", ""),
        "sources": result.get("sources", []),
        # bonus: expose the transcript so the client can display "You said: ..."
        "transcript": transcript,
    }