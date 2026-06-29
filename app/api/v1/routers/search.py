from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select
from app.db.session import get_db
from app.db.models.vector import ProductVector
from app.modules.search.service import SearchService
from app.modules.search.embeddings import EmbeddingService
from app.core.config import settings
from app.core.exceptions import (
    SearchServiceException,
    EmbeddingGenerationError,
    VectorSearchError,
    DatabaseError,
    LLMGenerationError,
    RateLimitError,
    ProductNotFoundError,
)
from app.api.v1.schemas import (
    ProductIndexRequest,
    ListIndexedRequest,
    GenerateKeyRequest,
    SearchRequest,
    RAGResponse,
)
import logging
import math
import hmac
import hashlib

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["AI Search"])


def get_active_provider() -> str:
    provider = settings.ACTIVE_PROVIDER
    logger.info("Using active provider: %s (from ACTIVE_PROVIDER env)", provider)
    return provider


def _generate_key(user_input: str) -> str:
    return hmac.new(
        settings.API_SECRET.encode("utf-8"),
        user_input.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


# ---------------------------------------------------------------------------
# Auth dependencies
# ---------------------------------------------------------------------------

def verify_api_key(request: Request):
    key_input = (request.headers.get("X-Key-Input") or "").strip()
    raw_key_header = request.headers.get("X-API-Key")
    auth_header = request.headers.get("Authorization", "")
    key = (raw_key_header or auth_header.replace("Bearer ", "")).strip()

    if not key_input:
        logger.warning("API key verification failed: missing X-Key-Input header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Key-Input header.",
        )

    expected_key = _generate_key(key_input)
    if not key or not hmac.compare_digest(key, expected_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
        )


def verify_generate_key(request: Request):
    key_input = request.headers.get("X-Key-Input", "").strip()
    key = request.headers.get("X-API-Key", "").strip()
    expected = _generate_key("generate")
    if key_input != "generate" or not key or not hmac.compare_digest(key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized.")


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _safe_float(v):
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _safe_int(v):
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return int(f)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# /generate-key
# ---------------------------------------------------------------------------

@router.post("/generate-key", summary="Generate API key from user input")
def generate_key(
    body: GenerateKeyRequest,
    _: None = Depends(verify_generate_key),
):
    return {"input": body.input, "token": _generate_key(body.input)}


# ---------------------------------------------------------------------------
# /indexed
# ---------------------------------------------------------------------------

async def _list_indexed_products(
    org_id: str | None, limit: int, db: AsyncSession
) -> JSONResponse:
    try:
        q = select(
            ProductVector.org_id,
            ProductVector.product_id,
            ProductVector.name,
            ProductVector.category,
            ProductVector.brand,
            ProductVector.description,
            ProductVector.specifications,
            ProductVector.price,
            ProductVector.rating,
            ProductVector.review_count,
            ProductVector.status,
        ).limit(limit)
        if org_id:
            q = q.where(ProductVector.org_id == org_id)
        q = q.order_by(ProductVector.org_id, ProductVector.product_id)

        result = await db.execute(q)
        rows = result.fetchall()

        items = [
            {
                "org_id":         r[0],
                "product_id":     r[1],
                "name":           r[2],
                "category":       r[3],
                "brand":          r[4],
                "description":    r[5],
                "specifications": r[6],
                "price":          _safe_float(r[7]),
                "rating":         _safe_float(r[8]),
                "review_count":   _safe_int(r[9]),
                "status":         r[10],
            }
            for r in rows
        ]
        return JSONResponse(
            content={"total": len(items), "org_id_filter": org_id, "items": items},
            media_type="application/json; charset=utf-8",
        )
    except Exception as e:
        logger.error("List indexed error: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list indexed products.",
        )


@router.post("/indexed", summary="List indexed products", response_model=None, status_code=200)
async def list_indexed(
    body: ListIndexedRequest,
    _: None = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    return await _list_indexed_products(org_id=body.org_id, limit=body.limit, db=db)


# ---------------------------------------------------------------------------
# /index  POST
# ---------------------------------------------------------------------------

@router.post("/index", status_code=status.HTTP_201_CREATED)
async def index_product(
    request: ProductIndexRequest,
    _: None = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    try:
        payload = request.model_dump()
        await SearchService.index_product(db, payload)
        return {
            "status":     "indexed",
            "org_id":     request.org_id,
            "product_id": request.product_id,
            "message":    f"Product '{request.name}' indexed successfully",
        }
    except RateLimitError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
    except EmbeddingGenerationError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Embedding service error: {e}")
    except DatabaseError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Database error: {e}")
    except SearchServiceException as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    except Exception as e:
        logger.error("Unexpected error in index_product: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An unexpected error occurred.")


# ---------------------------------------------------------------------------
# /index  PUT
# ---------------------------------------------------------------------------

@router.put("/index", status_code=status.HTTP_200_OK)
async def update_product(
    request: ProductIndexRequest,
    _: None = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    try:
        payload = request.model_dump()
        await SearchService.update_product(db, payload)
        return {
            "status":     "updated",
            "org_id":     request.org_id,
            "product_id": request.product_id,
            "message":    f"Product '{request.name}' updated successfully",
        }
    except ProductNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except RateLimitError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
    except EmbeddingGenerationError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Embedding service error: {e}")
    except DatabaseError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Database error: {e}")
    except Exception as e:
        logger.error("Unexpected error in update_product: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An unexpected error occurred.")


# ---------------------------------------------------------------------------
# /index  DELETE
# ---------------------------------------------------------------------------

@router.delete("/index", status_code=status.HTTP_200_OK)
async def delete_product(
    org_id:     str = Query(..., description="Organization ID"),
    product_id: str = Query(..., description="Product ID to delete"),
    _: None = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    try:
        await SearchService.delete_product(db, org_id, product_id)
        return {
            "status":     "deleted",
            "org_id":     org_id,
            "product_id": product_id,
            "message":    f"Product '{product_id}' deleted successfully",
        }
    except ProductNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except DatabaseError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Database error: {e}")
    except Exception as e:
        logger.error("Unexpected error in delete_product: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An unexpected error occurred.")


# ---------------------------------------------------------------------------
# /semantic
# ---------------------------------------------------------------------------

@router.post("/semantic")
async def semantic_search(
    request: SearchRequest,
    _: None = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    try:
        results = await SearchService.semantic_search(
            db,
            request.query,
            org_id=request.org_id,
            top_k=request.top_k,
            filters=request.filters,
        )
        return {"results": results, "query": request.query}
    except RateLimitError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
    except EmbeddingGenerationError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Embedding service error: {e}")
    except VectorSearchError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Search error: {e}")
    except DatabaseError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Database error: {e}")
    except SearchServiceException as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    except Exception as e:
        logger.error("Unexpected error in semantic_search: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An unexpected error occurred.")


# ---------------------------------------------------------------------------
# /rag
# ── Off-topic check is handled inside SearchService.rag_search() via the
#    intent gate (intent_gate.py). No pre-check needed here.
# ---------------------------------------------------------------------------

@router.post("/rag", response_model=RAGResponse)
async def rag_search(
    request: SearchRequest,
    provider: str | None = Query(
        None,
        description="LLM provider: 'gemini' or 'openai'. Defaults to ACTIVE_PROVIDER.",
    ),
    _: None = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    """
    RAG search with automatic fallback.
    - Uses the requested provider, or ACTIVE_PROVIDER if not specified.
    - On LLMGenerationError, retries with the other provider.
    - Off-topic queries are caught by the intent gate inside SearchService.
    - RateLimitError returns 429 immediately (no fallback).
    """
    if provider:
        provider = provider.lower().strip()
        if provider not in ("gemini", "openai"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Provider must be 'gemini' or 'openai'.",
            )
        selected_provider = provider
    else:
        selected_provider = get_active_provider()

    fallback_provider = "openai" if selected_provider == "gemini" else "gemini"

    logger.info(
        "RAG search — query: '%s', org_id: %s, provider: %s",
        request.query, request.org_id, selected_provider,
    )

    try:
        result = await SearchService.rag_search(
            db,
            request.query,
            org_id=request.org_id,
            llm_provider=selected_provider,
            top_k=request.top_k,
            filters=request.filters,
        )
        logger.info("RAG search completed using %s", selected_provider)
        return result

    except RateLimitError as e:
        logger.warning("Rate limit hit on provider '%s': %s", selected_provider, e)
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=f"Rate limit reached: {e}")

    except LLMGenerationError as e:
        logger.warning("LLM error on '%s': %s. Trying fallback '%s'", selected_provider, e, fallback_provider)
        try:
            result = await SearchService.rag_search(
                db,
                request.query,
                org_id=request.org_id,
                llm_provider=fallback_provider,
                top_k=request.top_k,
                filters=request.filters,
            )
            logger.info("Fallback provider '%s' succeeded", fallback_provider)
            return result
        except Exception as fallback_error:
            logger.error(
                "Both providers failed. Primary (%s): %s | Fallback (%s): %s",
                selected_provider, e, fallback_provider, fallback_error, exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI generation failed on all available providers.",
            )

    except EmbeddingGenerationError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Embedding service error: {e}")
    except VectorSearchError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Search error: {e}")
    except DatabaseError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Database error: {e}")
    except SearchServiceException as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    except Exception as e:
        logger.error("Unexpected error in rag_search: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An unexpected error occurred.")


# ---------------------------------------------------------------------------
# /debug
# ---------------------------------------------------------------------------

@router.post("/debug")
async def debug_search(
    request: SearchRequest,
    _: None = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    if not settings.DEBUG_MODE:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")

    try:
        query  = request.query
        org_id = request.org_id

        query_embedding = await EmbeddingService.embed(query)
        embedding_str   = "[" + ",".join(map(str, query_embedding)) + "]"

        sql = text("""
            SELECT
                org_id,
                product_id,
                name,
                category,
                brand,
                description,
                specifications,
                price,
                rating,
                review_count,
                status,
                1 - (embedding <=> CAST(:q AS vector))  AS similarity_score,
                embedding <-> CAST(:q AS vector)         AS euclidean_distance,
                embedding <=> CAST(:q AS vector)         AS cosine_distance
            FROM product_vectors
            WHERE (:org_id IS NULL OR org_id = :org_id)
            ORDER BY embedding <=> CAST(:q AS vector)
            LIMIT 10
        """)

        result = await db.execute(sql, {"q": embedding_str, "org_id": org_id})
        rows   = result.mappings().fetchall()

        query_words  = set(query.lower().split())
        debug_results = []
        for row in rows:
            product_text = " ".join(filter(None, [
                row["name"], row["category"], row["brand"],
                row["description"], row["specifications"],
            ])).lower()
            product_words  = set(product_text.split())
            matching_words = query_words.intersection(product_words)

            debug_results.append({
                "org_id":              row["org_id"],
                "product_id":          row["product_id"],
                "name":                row["name"],
                "category":            row["category"],
                "brand":               row["brand"],
                "description":         row["description"],
                "specifications":      row["specifications"],
                "price":               _safe_float(row["price"]),
                "rating":              _safe_float(row["rating"]),
                "review_count":        _safe_int(row["review_count"]),
                "status":              row["status"],
                "similarity_score":    _safe_float(row["similarity_score"]) or 0.0,
                "euclidean_distance":  _safe_float(row["euclidean_distance"]) or 0.0,
                "cosine_distance":     _safe_float(row["cosine_distance"]) or 0.0,
                "matching_words":      list(matching_words),
                "total_query_words":   len(query_words),
                "total_product_words": len(product_words),
            })

        return {"query": query, "query_words": list(query_words), "results": debug_results}

    except RateLimitError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
    except EmbeddingGenerationError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Embedding service error: {e}")
    except VectorSearchError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Search error: {e}")
    except DatabaseError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Database error: {e}")
    except Exception as e:
        logger.error("Unexpected error in debug_search: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Debug search failed.")