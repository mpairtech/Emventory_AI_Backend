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

# API key is generated from user input: key = HMAC(API_SECRET, user_input).hexdigest()
def _generate_key(user_input: str) -> str:
    if not settings.API_SECRET:
        return ""
    return hmac.new(
        settings.API_SECRET.encode("utf-8"),
        user_input.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

# If API_SECRET is set, client must send X-Key-Input (e.g. org_id) and X-API-Key = HMAC(API_SECRET, X-Key-Input)
def verify_api_key(request: Request):
    if not settings.API_SECRET:
        return
    key_input = request.headers.get("X-Key-Input", "").strip()
    key = request.headers.get("X-API-Key") or request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if not key_input:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Key-Input header (e.g. org_id). API key is generated from this input.",
        )
    expected_key = _generate_key(key_input)
    if not key or not hmac.compare_digest(key, expected_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing API key")


# To call /generate-key: send X-Key-Input: "generate" and X-API-Key: HMAC(API_SECRET, "generate")
def verify_generate_key(request: Request):
    if not settings.API_SECRET:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="API_SECRET not configured")
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
    return {"input": body.input, "api_key": _generate_key(body.input)}


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


@router.get("/indexed", summary="List indexed products (pgvector)")
def list_indexed(
    org_id: str | None = Query(None, description="Filter by org_id (MySQL org_id)"),
    limit: int = Query(100, ge=1, le=500),
    _: None = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    """Check what's stored in pgvector product_vectors. Returns all indexed fields (no embedding)."""
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


@router.post("/indexed/list", summary="List indexed products (POST with JSON body)")
def list_indexed_post(
    body: ListIndexedRequest,
    _: None = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    """Same as GET /indexed but accepts org_id and limit in JSON body. Use this in Postman with POST + body."""
    return list_indexed(org_id=body.org_id, limit=body.limit, db=db)


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
        results = SearchService.semantic_search(db, request.query, org_id=request.org_id)
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
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred"
        )


@router.post("/rag", response_model=RAGResponse)
def rag_search(
    request: SearchRequest,
    _: None = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    try:
        result = SearchService.rag_search(db, request.query, org_id=request.org_id)
        return result
    
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
    
    except LLMGenerationError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"AI generation error: {str(e)}"
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


@router.post("/debug")
def debug_search(
    request: SearchRequest,
    _: None = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
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