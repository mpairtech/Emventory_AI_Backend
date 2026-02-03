"""
Unified AI endpoint for NestJS: one service, model-based invoke.
Uses model registry so new models = register one handler (no long if-chain).
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.search.service import SearchService
from app.modules.search.embeddings import EmbeddingService
from app.api.v1.schemas import AIInvokeRequest, AIInvokeInput
from app.core.ai_registry import get_handler, register
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

router = APIRouter(prefix="/ai", tags=["AI Invoke (NestJS)"])


def _validate_input(req: AIInvokeRequest) -> None:
    """Ensure input has the right fields for the chosen model."""
    inp = req.input
    if req.model in ("rag", "semantic"):
        if not inp.query or not inp.query.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="input.query required for model=rag and model=semantic",
            )
    elif req.model == "embedding":
        if not inp.text or not inp.text.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="input.text required for model=embedding",
            )
    elif req.model == "index":
        if not inp.org_id or not inp.org_id.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="input.org_id required for model=index (MySQL org_id)",
            )
        if inp.product_id is None or not str(inp.product_id).strip() or not inp.name or not inp.category or inp.price is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="input.product_id, name, category, price required for model=index",
            )


# --- Model handlers (registry): add new model = add function + @register("name") ---

@register("rag")
def _handle_rag(inp: AIInvokeInput, db: Session) -> dict:
    org_id = (inp.org_id or "").strip() or None
    return SearchService.rag_search(db, inp.query.strip(), org_id=org_id)

@register("semantic")
def _handle_semantic(inp: AIInvokeInput, db: Session) -> dict:
    org_id = (inp.org_id or "").strip() or None
    results = SearchService.semantic_search(db, inp.query.strip(), org_id=org_id)
    return {"results": results, "query": inp.query}

@register("embedding")
def _handle_embedding(inp: AIInvokeInput, db: Session) -> dict:
    embedding = EmbeddingService.embed(inp.text.strip())
    return {"embedding": embedding, "dim": len(embedding)}

@register("index")
def _handle_index(inp: AIInvokeInput, db: Session) -> dict:
    payload = {
        "org_id": inp.org_id.strip(),
        "product_id": str(inp.product_id).strip(),
        "name": (inp.name or "").strip(),
        "category": (inp.category or "").strip(),
        "price": inp.price,
    }
    SearchService.index_product(db, payload)
    return {"status": "indexed", "org_id": inp.org_id, "product_id": inp.product_id, "message": f"Product '{inp.name}' indexed"}


@router.post("/invoke")
def ai_invoke(request: AIInvokeRequest, db: Session = Depends(get_db)):
    """
    Single entry for NestJS: call by model name. Dispatches via registry.
    """
    try:
        _validate_input(request)
        model, inp = request.model, request.input
        handler = get_handler(model)
        if not handler:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown model: {model}")
        result = handler(inp, db)
        return {"model": model, "result": result}

    except RateLimitError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
    except EmbeddingGenerationError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Embedding service error: {str(e)}",
        )
    except LLMGenerationError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"AI generation error: {str(e)}",
        )
    except VectorSearchError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Search error: {str(e)}")
    except DatabaseError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Database error: {str(e)}")
    except SearchServiceException as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI invoke error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred",
        )
