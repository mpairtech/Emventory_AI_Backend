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
    logger.info("Using active provider: %s (from ACTIVE_PROVIDER env)", provider)
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
            detail="Missing X-Key-Input header.",
        )

    expected_key = _generate_key(key_input)

    # Only log boolean outcome — never log key material, prefixes, or suffixes.
    logger.info(
        "verify_api_key: key_input=%r, key_present=%s",
        key_input,
        bool(key),
    )

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
        # Generic message — do not leak how the key scheme works
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized.",
        )


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
    """Convert to float for JSON; NaN/Inf -> None so clients get valid JSON."""
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
    """Convert to int for JSON; invalid/NaN/Inf -> None."""
    if v is None:
        return None
    try:
        f = float(v)
        # NaN/Inf check must happen on the float before casting to int,
        # since int values can never be NaN or Inf.
        if math.isnan(f) or math.isinf(f):
            return None
        return int(f)
    except (TypeError, ValueError):
        return None


def _list_indexed_products(org_id: str | None, limit: int, db: Session):
    """Helper to list indexed products."""
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
                "org_id":          r[0],
                "product_id":      r[1],
                "name":            r[2],
                "category":        r[3],
                "brand":           r[4],
                "description":     r[5],
                "specifications":  r[6],
                "price":           _safe_float(r[7]),
                "rating":          _safe_float(r[8]),
                "review_count":    _safe_int(r[9]),
                "status":          r[10],
            }
            for r in rows
        ]
        return JSONResponse(
            content={"total": total, "org_id_filter": org_id, "items": items},
            media_type="application/json; charset=utf-8",
        )
    except Exception as e:
        logger.error("List indexed error: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list indexed products.",
        )


# /indexed and /indexed/list were duplicate routes doing identical work.
# Consolidated into a single endpoint at /indexed.
@router.post(
    "/indexed",
    summary="List indexed products",
    response_model=None,
    status_code=200,
)
def list_indexed(
    body: ListIndexedRequest,
    _: None = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    """List indexed products, filtered by org_id and limited by limit."""
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
            "status":     "indexed",
            "org_id":     request.org_id,
            "product_id": request.product_id,
            "message":    f"Product '{request.name}' indexed successfully",
        }

    except RateLimitError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))

    except EmbeddingGenerationError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Embedding service error: {e}",
        )

    except DatabaseError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {e}",
        )

    except SearchServiceException as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    except Exception as e:
        logger.error("Unexpected error in index_product: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
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
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))

    except EmbeddingGenerationError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Embedding service error: {e}",
        )

    except VectorSearchError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search error: {e}",
        )

    except DatabaseError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {e}",
        )

    except SearchServiceException as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    except Exception as e:
        logger.error("Unexpected error in semantic_search: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
        )


@router.post("/rag", response_model=RAGResponse)
def rag_search(
    request: SearchRequest,
    provider: str | None = Query(
        None,
        description="LLM provider: 'gemini' or 'openai'. Defaults to ACTIVE_PROVIDER env variable.",
    ),
    _: None = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    """
    RAG search with automatic fallback.
    - Uses the requested provider, or ACTIVE_PROVIDER if not specified.
    - On LLMGenerationError, retries with the other provider.
    - RateLimitError does NOT trigger a fallback — it returns 429 immediately,
      since the fallback provider is likely also rate-limited or would waste quota.
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
        result = SearchService.rag_search(
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
        # Do not fall back on rate limit — failing fast is cheaper and more honest.
        logger.warning("Rate limit hit on provider '%s': %s", selected_provider, e)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit reached: {e}",
        )

    except LLMGenerationError as e:
        # LLM error is worth retrying on the fallback provider.
        logger.warning(
            "LLM error on '%s': %s. Trying fallback '%s'",
            selected_provider, e, fallback_provider,
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
            logger.info("Fallback provider '%s' succeeded", fallback_provider)
            return result
        except Exception as fallback_error:
            logger.error(
                "Both providers failed. Primary (%s): %s | Fallback (%s): %s",
                selected_provider, e, fallback_provider, fallback_error,
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI generation failed on all available providers.",
            )

    except EmbeddingGenerationError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Embedding service error: {e}",
        )

    except VectorSearchError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search error: {e}",
        )

    except DatabaseError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {e}",
        )

    except SearchServiceException as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    except Exception as e:
        logger.error("Unexpected error in rag_search: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred.",
        )


@router.post("/debug")
def debug_search(
    request: SearchRequest,
    _: None = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    # Guard: only available in DEBUG_MODE. Never expose in production.
    if not settings.DEBUG_MODE:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")

    try:
        query = request.query
        org_id = request.org_id
        query_embedding = EmbeddingService.embed(query)

        # Build the embedding string for pgvector — this is model output, not user input,
        # but we still pass it as a bound parameter to enforce parameterised query discipline
        # across the entire codebase. Never interpolate anything into SQL via f-strings.
        embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"

        # FIX (Critical — SQL Injection): The original code used an f-string to splice
        # `where_clause` directly into the SQL text:
        #
        #   where_clause = "WHERE org_id = :org_id" if org_id else ""
        #   sql = text(f"... {where_clause} ...")
        #
        # Although :org_id itself was still a bound parameter, the f-string interpolation
        # of the entire WHERE clause string means the SQL structure was determined by a
        # variable derived from user input. Any future refactor that accidentally put
        # org_id into the f-string directly (rather than via :org_id) would be a live
        # injection vulnerability. The pattern also normalises f-string SQL construction
        # in the codebase, which is how injection vectors spread.
        #
        # Fix: use a single static SQL template with a NULL-safe conditional parameter.
        # `:org_id IS NULL OR org_id = :org_id` evaluates to TRUE for all rows when
        # org_id is None (passed as SQL NULL), and filters to the specific org when set.
        # The SQL text is now a compile-time constant — no runtime string construction,
        # no f-strings, no branching SQL structure.
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

        # org_id is passed directly; SQLAlchemy binds it as a typed parameter.
        # When org_id is None, the DB receives NULL and the IS NULL branch fires,
        # returning rows across all orgs (intended debug behaviour).
        rows = db.execute(sql, {"q": embedding_str, "org_id": org_id}).mappings().fetchall()

        query_words = set(query.lower().split())

        debug_results = []
        for row in rows:
            # Use named column access via mappings() — never positional indices.
            # Positional access (row[11]) breaks silently if the SELECT column order
            # changes; named access raises a KeyError immediately on mismatch.
            product_text = " ".join(filter(None, [
                row["name"],
                row["category"],
                row["brand"],
                row["description"],
                row["specifications"],
            ])).lower()
            product_words = set(product_text.split())
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

        return {
            "query":       query,
            "query_words": list(query_words),
            "results":     debug_results,
        }

    except RateLimitError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))

    except EmbeddingGenerationError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Embedding service error: {e}",
        )

    except VectorSearchError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search error: {e}",
        )

    except DatabaseError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {e}",
        )

    except Exception as e:
        logger.error("Unexpected error in debug_search: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Debug search failed.",
        )