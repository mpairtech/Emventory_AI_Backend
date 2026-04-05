from fastapi import APIRouter, Header, HTTPException, Depends, Query, status
from typing import Optional
from app.api.v1.routers.search import router as search_router
from app.api.v1.routers.content import router as content_router
from app.core.cache.cache_service import cache_service
from app.api.v1.schemas import R2VoiceSearchRequest
from app.modules.search.stt import transcribe_from_r2
from sqlalchemy.orm import Session
from app.db.session import get_db

# ── These were missing ──────────────────────────────────────────────────────
from app.modules.search.service import SearchService
from app.api.v1.routers.search import get_active_provider
from app.core.exceptions import (
    AudioProcessingError,
    SpeechToTextError,
    EmbeddingGenerationError,
    VectorSearchError,
    DatabaseError,
    LLMGenerationError,
    RateLimitError,
    SearchServiceException,
)
import logging

logger = logging.getLogger(__name__)
# ───────────────────────────────────────────────────────────────────────────

router = APIRouter()


# -----------------------------------------------
# Dependency: API Key + optional Org ID
# -----------------------------------------------
async def verify_api_key(
    x_api_key: Optional[str] = Header(None),
    x_org_id: Optional[str] = Header(None),
):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key missing")
    return {"api_key": x_api_key, "org_id": x_org_id}


# -----------------------------------------------
# Include existing search router
# -----------------------------------------------
router.include_router(
    search_router,
    dependencies=[Depends(verify_api_key)]
)
router.include_router(
    content_router,                          
    dependencies=[Depends(verify_api_key)]   
)


# -----------------------------------------------
# Cache Management Endpoints
# -----------------------------------------------
@router.get("/cache/stats", summary="Get cache statistics")
def get_cache_stats(
    org_id: str | None = Query(None, description="Organization ID to check stats for"),
    _: None = Depends(verify_api_key),
):
    stats = cache_service.get_cache_stats(org_id=org_id)
    return stats


@router.post("/cache/invalidate", summary="Invalidate cache for an organization")
def invalidate_cache(
    org_id: str = Query(..., description="Organization ID to invalidate cache for"),
    _: None = Depends(verify_api_key),
):
    success = cache_service.invalidate_org(org_id)
    if success:
        return {"status": "success", "message": f"Cache invalidated for org_id={org_id}"}
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to invalidate cache"
        )


@router.post("/cache/clear", summary="Clear all cache (admin only)")
def clear_all_cache(
    confirm: bool = Query(False, description="Must be true to confirm clearing all cache"),
    _: None = Depends(verify_api_key),
):
    if not confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must set confirm=true to clear all cache"
        )
    success = cache_service.clear_all_cache()
    if success:
        return {"status": "success", "message": "All cache cleared"}
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clear cache"
        )


# -----------------------------------------------
# Voice Search
# -----------------------------------------------
@router.post("/voice")
async def voice_search(
    request: R2VoiceSearchRequest,
    _: None = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    """
    Voice search via Cloudflare R2.
    Pipeline: R2 URL → download → STT (gpt-4o-mini-transcribe) → RAG search
    """
    # 1. Transcribe
    try:
        transcript = await transcribe_from_r2(request.file_url, request.language)
    except AudioProcessingError as e:
        status_code = (
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
            if "25MB" in str(e)
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(status_code=status_code, detail=str(e))
    except SpeechToTextError as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS
            if "rate limit" in str(e).lower()
            else status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )

    if not transcript:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Transcription returned empty text. Check audio quality or language code.",
        )

    logger.info(f"[VoiceSearch] org={request.org_id} | transcript='{transcript[:120]}'")

    # 2. Resolve provider (mirrors /rag logic with fallback)
    if request.provider:
        provider = request.provider.lower().strip()
        if provider not in ["gemini", "openai"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Provider must be 'gemini' or 'openai'",
            )
    else:
        provider = get_active_provider()

    fallback_provider = "openai" if provider == "gemini" else "gemini"

    # 3. RAG pipeline
    try:
        result = SearchService.rag_search(
            db,
            transcript,
            org_id=request.org_id,
            llm_provider=provider,
            top_k=request.top_k,
            filters=request.filters,
        )
        return {
            "transcript": transcript,
            "answer": result["answer"],
            "sources": result["sources"],
        }

    except (LLMGenerationError, RateLimitError) as e:
        logger.warning(f"[VoiceSearch] Provider '{provider}' failed, trying '{fallback_provider}': {e}")
        try:
            result = SearchService.rag_search(
                db,
                transcript,
                org_id=request.org_id,
                llm_provider=fallback_provider,
                top_k=request.top_k,
                filters=request.filters,
            )
            return {
                "transcript": transcript,
                "answer": result["answer"],
                "sources": result["sources"],
            }
        except Exception as fallback_err:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Both providers failed: {str(fallback_err)}",
            )

    except (EmbeddingGenerationError, VectorSearchError, DatabaseError, SearchServiceException) as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    except Exception as e:
        logger.error(f"[VoiceSearch] Unexpected error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred",
        )