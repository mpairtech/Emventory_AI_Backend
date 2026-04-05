from fastapi import APIRouter, Depends, HTTPException, status
from app.api.v1.routers.search import verify_api_key
from app.api.v1.schemas import (
    ContentGenerationRequest,
    ContentGenerationResponse,
    GeneratedContent,
)
from app.modules.content.service import ContentGenerationService
from app.core.exceptions import LLMGenerationError, RateLimitError
from app.core.cache.cache_service import cache_service
import hashlib
import json
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/content", tags=["AI Content Generation"])

CONTENT_CACHE_TTL = 3600  # 1 hour


def _build_field_key(request: ContentGenerationRequest) -> str:
    """Deterministic SHA256 field key from all inputs that affect output."""
    pd = request.product_data
    raw = json.dumps({
        "name":           pd.name,
        "category":       pd.category,
        "brand":          pd.brand,
        "specifications": sorted(pd.specifications),
        "price":          pd.price,
        "query":          request.query,
        "region":         request.region,
        "language":       request.language,
        "tone":           request.tone,
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@router.post(
    "/generate",
    response_model=ContentGenerationResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate ecommerce product description and feature bullets",
)
def generate_content(
    request: ContentGenerationRequest,
    _: None = Depends(verify_api_key),
):
    pd = request.product_data
    field_key = _build_field_key(request)

    # ── 1. Cache read ──────────────────────────────────────────────────────
    try:
        cached = cache_service.get_content(field_key)
        if cached:
            return ContentGenerationResponse(**cached)
    except Exception as e:
        logger.warning("[ContentGen] Cache read error: %s", e)

    # ── 2. Generate via OpenAI ─────────────────────────────────────────────
    try:
        result = ContentGenerationService.generate(
            name=pd.name,
            category=pd.category,
            brand=pd.brand,
            specifications=pd.specifications,
            price=pd.price,
            region=request.region,
            language=request.language,
            tone=request.tone,
            query=request.query,
        )

    except RateLimitError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))

    except LLMGenerationError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))

    except Exception as e:
        logger.error("[ContentGen] Unexpected error: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Content generation failed unexpectedly",
        )

    # ── 3. Build response ──────────────────────────────────────────────────
    desc = result["description"]

    response = ContentGenerationResponse(
        product_name=pd.name,
        language=request.language,
        region=request.region,
        tone=request.tone,
        description=GeneratedContent(
            content=desc,
            word_count=len(desc.split()),
            char_count=len(desc),
        ),
        feature_bullets=result["feature_bullets"],
        provider="openai",
    )

    # ── 4. Cache write ─────────────────────────────────────────────────────
    try:
        cache_service.set_content(field_key, response.model_dump(), ttl=CONTENT_CACHE_TTL)
    except Exception as e:
        logger.warning("[ContentGen] Cache write error: %s", e)

    return response