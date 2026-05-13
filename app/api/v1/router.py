from fastapi import APIRouter, Header, HTTPException, Depends, Query, status
from typing import Optional
from app.api.v1.routers.search import router as search_router
from app.api.v1.routers.content import router as content_router

from app.core.cache.cache_service import cache_service
from app.api.v1.schemas import R2VoiceSearchRequest
from app.modules.search.stt import transcribe_from_r2
from sqlalchemy.orm import Session
from app.db.session import get_db

from app.modules.search.service import SearchService
from app.api.v1.routers.search import get_active_provider
from app.core.config import settings
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

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# R2 lazy singleton
# ---------------------------------------------------------------------------

_r2_client = None


def _get_r2_client():
    global _r2_client
    if _r2_client is None:
        _r2_client = boto3.client(
            "s3",
            endpoint_url=settings.R2_ENDPOINT_URL,
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            region_name="auto",
        )
    return _r2_client


def _delete_from_r2(file_key: str) -> bool:
    if not all([
        settings.R2_ENDPOINT_URL,
        settings.R2_ACCESS_KEY_ID,
        settings.R2_SECRET_ACCESS_KEY,
        settings.R2_BUCKET_NAME,
    ]):
        raise AudioProcessingError("R2 credentials are not fully configured")

    try:
        client = _get_r2_client()
        client.delete_object(
            Bucket=settings.R2_BUCKET_NAME,
            Key=file_key,
        )
        logger.info(f"[R2] Deleted: bucket={settings.R2_BUCKET_NAME} | key={file_key}")
        return True

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg  = e.response["Error"]["Message"]
        logger.error(f"[R2] ClientError deleting '{file_key}': {error_code} — {error_msg}")
        raise AudioProcessingError(f"R2 deletion failed: {error_code} — {error_msg}")

    except BotoCoreError as e:
        logger.error(f"[R2] BotoCoreError deleting '{file_key}': {e}")
        raise AudioProcessingError(f"R2 connection error: {str(e)}")

    except Exception as e:
        logger.error(f"[R2] Unexpected error deleting '{file_key}': {e}", exc_info=True)
        raise AudioProcessingError(f"Unexpected R2 error: {str(e)}")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class R2DeleteRequest(BaseModel):
    file_key: str
    org_id:   str


# ---------------------------------------------------------------------------
# Dependency: API Key + optional Org ID
# ---------------------------------------------------------------------------

async def verify_api_key(
    x_api_key: Optional[str] = Header(None),
    x_org_id: Optional[str] = Header(None),
):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key missing")
    return {"api_key": x_api_key, "org_id": x_org_id}


# ---------------------------------------------------------------------------
# Include existing routers
# ---------------------------------------------------------------------------

router.include_router(
    search_router,
    dependencies=[Depends(verify_api_key)]
)
router.include_router(
    content_router,
    dependencies=[Depends(verify_api_key)]
)


# ---------------------------------------------------------------------------
# Cache Management Endpoints
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Voice Search
# ---------------------------------------------------------------------------

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

    # 2. Resolve provider
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
        result = await SearchService.rag_search(
            db,
            transcript,
            org_id=request.org_id,
            llm_provider=provider,
            top_k=request.top_k,
            filters=request.filters,
        )
        return {
            "transcript": transcript,
            "answer":     result["answer"],
            "sources":    result["sources"],
        }

    except (LLMGenerationError, RateLimitError) as e:
        logger.warning(f"[VoiceSearch] Provider '{provider}' failed, trying '{fallback_provider}': {e}")
        try:
            result = await SearchService.rag_search(
                db,
                transcript,
                org_id=request.org_id,
                llm_provider=fallback_provider,
                top_k=request.top_k,
                filters=request.filters,
            )
            return {
                "transcript": transcript,
                "answer":     result["answer"],
                "sources":    result["sources"],
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


# ---------------------------------------------------------------------------
# Delete R2 Audio File
# ---------------------------------------------------------------------------

@router.delete("/voice/audio", status_code=status.HTTP_200_OK)
async def delete_audio(
    body: R2DeleteRequest,
    _: None = Depends(verify_api_key),
):
    """
    Delete an audio file from Cloudflare R2 by its object key.
    file_key is the filename only e.g. 'harvard.wav' — not the full URL.
    """
    logger.info(f"[R2Delete] org={body.org_id} | key={body.file_key}")

    try:
        _delete_from_r2(body.file_key)
        return {
            "status":   "deleted",
            "org_id":   body.org_id,
            "file_key": body.file_key,
            "message":  f"Audio file '{body.file_key}' deleted from R2 successfully",
        }

    except AudioProcessingError as e:
        logger.warning(f"[R2Delete] Failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )

    except Exception as e:
        logger.error(f"[R2Delete] Unexpected error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error during R2 deletion.",
        )