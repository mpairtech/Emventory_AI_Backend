from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict

from app.db.session import get_db
from app.modules.search.service import SearchService
from app.api.v1.router import verify_api_key
from app.core.exceptions import (
    SearchServiceException,
    EmbeddingGenerationError,
    VectorSearchError,
    DatabaseError,
    LLMGenerationError,
    RateLimitError,
)
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/revoke")




class PipelineRequest(BaseModel):
    
    org_id: str = Field(..., description="Organization ID (tenant key)")
    product_id: str = Field(..., description="Unique product identifier")
    name: str = Field(..., description="Product name")
    category: Optional[str] = None
    brand: Optional[str] = None
    description: Optional[str] = None
    specifications: Optional[str] = None
    price: Optional[float] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    status: Optional[str] = None

    
    query: str = Field(..., description="Search query to run after indexing")

    
    skip_index: bool = Field(
        False,
        description="Set true to skip re-indexing (product already indexed)"
    )
    include_semantic: bool = Field(
        True,
        description="Include raw semantic search results in response"
    )
    llm_provider: Optional[str] = Field(
        None,
        description="LLM provider: 'gemini' or 'openai'. Defaults to ACTIVE_PROVIDER env var."
    )


class PipelineStageStatus(BaseModel):
    success: bool
    message: str
    detail: Optional[str] = None


class PipelineResponse(BaseModel):
    org_id: str
    product_id: str
    query: str

    stages: Dict[str, PipelineStageStatus]

    # RAG answer (always present if pipeline succeeds)
    answer: Optional[str] = None
    sources: Optional[List[Dict[str, Any]]] = None

    # Optional raw semantic hits
    semantic_results: Optional[List[Dict[str, Any]]] = None

    provider_used: Optional[str] = None


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _resolve_provider(requested: Optional[str]) -> str:
    """Return a validated provider string, falling back to ACTIVE_PROVIDER."""
    from app.core.config import settings

    if requested:
        p = requested.lower().strip()
        if p not in ("gemini", "openai"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="llm_provider must be 'gemini' or 'openai'",
            )
        return p
    return settings.ACTIVE_PROVIDER


# ──────────────────────────────────────────────
# Unified Revoke Endpoint
# ──────────────────────────────────────────────

@router.post(
    "/run",
    response_model=PipelineResponse,
    status_code=status.HTTP_200_OK,
    summary="Index a product, run semantic search, then RAG – all in one call",
)
def run_pipeline(
    request: PipelineRequest,
    _: None = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    
    stages: Dict[str, PipelineStageStatus] = {}
    provider = _resolve_provider(request.llm_provider)

    # ── Stage 1: Index ────────────────────────────────────────────
    if request.skip_index:
        stages["index"] = PipelineStageStatus(
            success=True, message="Skipped (skip_index=true)"
        )
        logger.info(f"[revoke] index skipped | product={request.product_id}")
    else:
        try:
            payload = request.model_dump(
                exclude={"query", "skip_index", "include_semantic", "llm_provider"}
            )
            SearchService.index_product(db, payload)
            stages["index"] = PipelineStageStatus(
                success=True,
                message=f"Product '{request.name}' indexed successfully",
            )
            logger.info(f"[revoke] indexed | product={request.product_id} org={request.org_id}")
        except RateLimitError as e:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
        except EmbeddingGenerationError as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Embedding error during indexing: {str(e)}",
            )
        except (DatabaseError, SearchServiceException) as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Indexing failed: {str(e)}",
            )

    # ── Stage 2: Semantic Search ──────────────────────────────────
    semantic_results: Optional[List[Dict[str, Any]]] = None

    if request.include_semantic:
        try:
            semantic_data = SearchService.semantic_search(
                db, request.query, org_id=request.org_id
            )
            semantic_results = semantic_data
            stages["semantic_search"] = PipelineStageStatus(
                success=True,
                message=f"Found {len(semantic_results)} semantic matches",
            )
            logger.info(
                f"[revoke] semantic | hits={len(semantic_results)} query='{request.query}'"
            )
        except (EmbeddingGenerationError, VectorSearchError, DatabaseError, SearchServiceException) as e:
            # Non-fatal – log and continue to RAG
            stages["semantic_search"] = PipelineStageStatus(
                success=False,
                message="Semantic search failed (non-fatal)",
                detail=str(e),
            )
            logger.warning(f"[revoke] semantic search error (continuing): {e}")
    else:
        stages["semantic_search"] = PipelineStageStatus(
            success=True, message="Skipped (include_semantic=false)"
        )

    # ── Stage 3: RAG ─────────────────────────────────────────────
    answer: Optional[str] = None
    sources: Optional[List[Dict[str, Any]]] = None
    fallback_provider = "openai" if provider == "gemini" else "gemini"

    try:
        rag_result = SearchService.rag_search(
            db, request.query, org_id=request.org_id, llm_provider=provider
        )
        answer = rag_result.get("answer")
        sources = rag_result.get("sources", [])
        stages["rag"] = PipelineStageStatus(
            success=True,
            message=f"RAG completed using provider '{provider}'",
        )
        logger.info(f"[revoke] RAG done | provider={provider}")

    except (LLMGenerationError, RateLimitError) as e:
        logger.warning(f"[revoke] provider '{provider}' failed: {e}. Trying '{fallback_provider}'")
        try:
            rag_result = SearchService.rag_search(
                db, request.query, org_id=request.org_id, llm_provider=fallback_provider
            )
            answer = rag_result.get("answer")
            sources = rag_result.get("sources", [])
            provider = fallback_provider
            stages["rag"] = PipelineStageStatus(
                success=True,
                message=f"RAG completed using fallback provider '{fallback_provider}'",
            )
        except Exception as fallback_err:
            stages["rag"] = PipelineStageStatus(
                success=False,
                message="RAG failed on both providers",
                detail=f"Primary: {str(e)} | Fallback: {str(fallback_err)}",
            )
            if isinstance(e, RateLimitError):
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Both providers rate-limited: {str(e)}",
                )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"RAG failed on both providers: {str(e)}",
            )

    except (EmbeddingGenerationError, VectorSearchError, DatabaseError, SearchServiceException) as e:
        stages["rag"] = PipelineStageStatus(success=False, message="RAG error", detail=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"RAG pipeline error: {str(e)}",
        )

    except Exception as e:
        logger.error(f"[revoke] unexpected error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected pipeline error",
        )

    # ── Assemble response ─────────────────────────────────────────
    return PipelineResponse(
        org_id=request.org_id,
        product_id=request.product_id,
        query=request.query,
        stages=stages,
        answer=answer,
        sources=sources,
        semantic_results=semantic_results if request.include_semantic else None,
        provider_used=provider,
    )