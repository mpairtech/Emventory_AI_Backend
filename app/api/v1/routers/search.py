from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
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
    """
    Get the active LLM provider from settings.
    Returns 'gemini' or 'openai' based on ACTIVE_PROVIDER env variable.
    Settings already validates and normalizes the value, so we can use it directly.
    """
    provider = settings.ACTIVE_PROVIDER
    logger.info(f"Using active provider: {provider} (from ACTIVE_PROVIDER env)")
    return provider


# API key is generated from user input: key = HMAC(API_SECRET, user_input).hexdigest()
def _generate_key(user_input: str) -> str:
    return hmac.new(
        settings.API_SECRET.encode("utf-8"),
        user_input.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


# API_SECRET is required. Client must send X-Key-Input (e.g. org_id) and X-API-Key = HMAC(API_SECRET, X-Key-Input)
def verify_api_key(request: Request):
    """
    Verify API key coming from client.
    This extra logging is only to help local debugging; remove or reduce in production.
    """
    key_input = (request.headers.get("X-Key-Input") or "").strip()
    raw_key_header = request.headers.get("X-API-Key")
    auth_header = request.headers.get("Authorization", "")

    key = (raw_key_header or auth_header.replace("Bearer ", "")).strip()

    if not key_input:
        logger.warning("API key verification failed: missing X-Key-Input header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Key-Input header (e.g. org_id). API key is generated from this input.",
        )

    expected_key = _generate_key(key_input)

    # Debug log: only lengths + prefix/suffix to avoid full secret exposure
    logger.info(
        "verify_api_key: key_input='%s', received_len=%s, expected_len=%s, "
        "received_prefix='%s', expected_prefix='%s'",
        key_input,
        len(key) if key else 0,
        len(expected_key),
        (key or "")[:6],
        expected_key[:6],
    )

    if not key or not hmac.compare_digest(key, expected_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing API key")


# To call /generate-key: send X-Key-Input: "generate" and X-API-Key: HMAC(API_SECRET, "generate")
def verify_generate_key(request: Request):
    key_input = request.headers.get("X-Key-Input", "").strip()
    key = request.headers.get("X-API-Key", "").strip()
    expected = _generate_key("generate")
    if key_input != "generate" or not key or not hmac.compare_digest(key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Use X-Key-Input: generate and X-API-Key: HMAC(API_SECRET, 'generate')")


@router.post("/generate-key", summary="Generate API key from user input")
def generate_key(
    body: GenerateKeyRequest,
    _: None = Depends(verify_generate_key),
):
    """
    Returns API key for the given input. Key = HMAC(API_SECRET, input).
    To call this: send X-Key-Input: "generate" and X-API-Key: HMAC(API_SECRET, "generate").
    """
    return {"input": body.input, "token": _generate_key(body.input)}


def _safe_float(v):
    """Convert to float for JSON; NaN/Inf -> None so Postman and other clients get valid JSON."""
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
    """Convert to int for JSON; invalid/NaN -> None."""
    if v is None:
        return None
    try:
        x = int(float(v))
        if math.isnan(x) or math.isinf(x):
            return None
        return x
    except (TypeError, ValueError):
        return None


def _list_indexed_products(org_id: str | None, limit: int, db: Session):
    """Helper function to list indexed products."""
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
        rows = db.execute(q).fetchall()
        total = len(rows)
        items = [
            {
                "org_id": r[0],
                "product_id": r[1],
                "name": r[2],
                "category": r[3],
                "brand": r[4],
                "description": r[5],
                "specifications": r[6],
                "price": _safe_float(r[7]),
                "rating": _safe_float(r[8]),
                "review_count": _safe_int(r[9]),
                "status": r[10]
            }
            for r in rows
        ]
        # Explicit JSONResponse with charset so Postman/other clients parse correctly
        return JSONResponse(
            content={"total": total, "org_id_filter": org_id, "items": items},
            media_type="application/json; charset=utf-8",
        )
    except Exception as e:
        logger.error(f"List indexed error: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post(
    "/indexed",
    summary="List indexed products (POST with JSON body)",
    response_model=None,
    status_code=200
)
def list_indexed_post_direct(
    body: ListIndexedRequest,
    _: None = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    """List indexed products accepting org_id and limit in JSON body."""
    return _list_indexed_products(org_id=body.org_id, limit=body.limit, db=db)


@router.post("/indexed/list", summary="List indexed products (POST with JSON body)")
def list_indexed_post(
    body: ListIndexedRequest,
    _: None = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    """Same as GET /indexed but accepts org_id and limit in JSON body. Use this in Postman with POST + body."""
    return _list_indexed_products(org_id=body.org_id, limit=body.limit, db=db)


@router.post("/index", status_code=status.HTTP_201_CREATED)
def index_product(
    request: ProductIndexRequest,
    _: None = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    try:
        payload = request.model_dump()
        SearchService.index_product(db, payload)

        return {
            "status": "indexed",
            "org_id": request.org_id,
            "product_id": request.product_id,
            "message": f"Product '{request.name}' indexed successfully"
        }

    except RateLimitError as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(e)
        )

    except EmbeddingGenerationError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Embedding service error: {str(e)}"
        )

    except DatabaseError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )

    except SearchServiceException as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred"
        )


@router.post("/semantic")
def semantic_search(
    request: SearchRequest,
    _: None = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    try:
        results = SearchService.semantic_search(
            db,
            request.query,
            org_id=request.org_id,
            top_k=request.top_k,
            filters=request.filters,
        )
        return {"results": results, "query": request.query}

    except RateLimitError as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(e)
        )

    except EmbeddingGenerationError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Embedding service error: {str(e)}"
        )

    except VectorSearchError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search error: {str(e)}"
        )

    except DatabaseError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )

    except SearchServiceException as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred"
        )


@router.post("/rag", response_model=RAGResponse)
def rag_search(
    request: SearchRequest,
    provider: str | None = Query(None, description="LLM provider: 'gemini' or 'openai'. If not provided, uses ACTIVE_PROVIDER env variable."),
    _: None = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    """
    RAG search endpoint that supports provider selection.
    - If provider query parameter is provided, uses that provider.
    - Otherwise, uses the active provider from ACTIVE_PROVIDER env variable.
    - Falls back to the other provider if the selected one fails.
    """
    if provider:
        provider = provider.lower().strip()
        if provider not in ["gemini", "openai"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Provider must be either 'gemini' or 'openai'"
            )
        selected_provider = provider
    else:
        selected_provider = get_active_provider()

    fallback_provider = "openai" if selected_provider == "gemini" else "gemini"

    logger.info(f"RAG search request - Query: '{request.query}', Org ID: {request.org_id}, Using provider: {selected_provider}")

    try:
        result = SearchService.rag_search(
            db,
            request.query,
            org_id=request.org_id,
            llm_provider=selected_provider,
            top_k=request.top_k,
            filters=request.filters,
        )
        logger.info(f"RAG search completed successfully using {selected_provider}")
        return result

    except (LLMGenerationError, RateLimitError) as e:
        logger.warning(
            f"Provider '{selected_provider}' failed: {str(e)}. Trying fallback '{fallback_provider}'"
        )
        try:
            result = SearchService.rag_search(
                db,
                request.query,
                org_id=request.org_id,
                llm_provider=fallback_provider,
                top_k=request.top_k,
                filters=request.filters,
            )
            logger.info(f"Fallback provider '{fallback_provider}' succeeded")
            return result
        except Exception as fallback_error:
            logger.error(f"Both active and fallback providers failed. Original: {str(e)}, Fallback: {str(fallback_error)}")
            if isinstance(e, RateLimitError):
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Both providers rate limited. Original: {str(e)}"
                )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"AI generation error (both providers failed): {str(e)}"
            )

    except EmbeddingGenerationError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Embedding service error: {str(e)}"
        )

    except VectorSearchError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search error: {str(e)}"
        )

    except DatabaseError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )

    except SearchServiceException as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred"
        )


@router.post("/debug")
def debug_search(
    request: SearchRequest,
    _: None = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    #if not settings.DEBUG_MODE:
        #raise HTTPException(status_code=404, detail="Not found")

    try:
        query = request.query
        org_id = request.org_id
        query_embedding = EmbeddingService.embed(query)

        embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'
        params = {"q": embedding_str}
        where_clause = "WHERE org_id = :org_id" if org_id else ""
        if org_id:
            params["org_id"] = org_id

        sql = text(f"""
            SELECT 
                org_id, product_id,
                name,
                category,
                brand,
                description,
                specifications,
                price,
                rating,
                review_count,
                status,
                1 - (embedding <=> CAST(:q AS vector)) AS similarity_score,
                embedding <-> CAST(:q AS vector) AS euclidean_distance,
                embedding <=> CAST(:q AS vector) AS cosine_distance
            FROM product_vectors
            {where_clause}
            ORDER BY embedding <=> CAST(:q AS vector)
            LIMIT 10
        """)

        results = db.execute(sql, params).fetchall()

        query_words = set(query.lower().split())

        debug_results = []
        for row in results:
            # Build product text from all searchable fields
            product_text_parts = [row[2] or "", row[3] or "", row[4] or "", row[5] or "", row[6] or ""]
            product_text = " ".join(product_text_parts).lower()
            product_words = set(product_text.split())
            matching_words = query_words.intersection(product_words)

            debug_results.append({
                "org_id": row[0],
                "product_id": row[1],
                "name": row[2],
                "category": row[3],
                "brand": row[4],
                "description": row[5],
                "specifications": row[6],
                "price": _safe_float(row[7]),
                "rating": _safe_float(row[8]),
                "review_count": _safe_int(row[9]),
                "status": row[10],
                "similarity_score": _safe_float(row[11]) or 0.0,
                "cosine_distance": _safe_float(row[13]) or 0.0,
                "matching_words": list(matching_words),
                "total_query_words": len(query_words),
                "total_product_words": len(product_words)
            })

        return {
            "query": query,
            "query_words": list(query_words),
            "results": debug_results
        }

    except RateLimitError as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(e)
        )

    except EmbeddingGenerationError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Embedding service error: {str(e)}"
        )

    except VectorSearchError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search error: {str(e)}",
        )
    except DatabaseError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}",
        )
    except Exception as e:
        logger.error(f"Error in debug search: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Debug search failed",
        )