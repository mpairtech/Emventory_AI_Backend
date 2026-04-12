from fastapi import APIRouter, Depends, HTTPException, status
from app.api.v1.routers.search import verify_api_key
from app.api.v1.schemas import (
    ContentGenerationRequest,
    ContentGenerationResponse,
    GeneratedContent,
    SocialPostRequest,
    SocialPostResponse,
    SocialPostContent,
)
from app.modules.content.service import ContentGenerationService
from app.core.exceptions import LLMGenerationError, RateLimitError
from app.core.cache.cache_service import cache_service
import hashlib
import json
import logging
import uuid

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/content", tags=["AI Content"])

CONTENT_CACHE_TTL_SECONDS = 3600  # 1 hour — applies to both /generate and /social


# ── Cache key builder ──────────────────────────────────────────────────────

def _build_cache_key(request: ContentGenerationRequest | SocialPostRequest, namespace: str) -> str:
    """
    Deterministic SHA-256 cache key derived from all inputs that affect LLM output.

    `namespace` prevents key collisions between different endpoint types
    (e.g. 'generate' vs 'social').
    """
    product = request.product_data
    specs = product.specifications

    # Normalize specifications regardless of whether they are strings or dicts.
    # Sorting plain strings directly is safe; dicts must be sorted by a stable field.
    if specs and isinstance(specs[0], dict):
        sorted_specs = sorted(specs, key=lambda x: x["key"])
    else:
        sorted_specs = sorted(specs)

    payload = json.dumps(
        {
            "name":           product.name,
            "category":       product.category,
            "brand":          product.brand,
            "specifications": sorted_specs,
            "price":          product.price,
            "query":          request.query,
            "region":         request.region,
            "language":       request.language,
            "tone":           request.tone,
            "namespace":      namespace,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ── Shared cache/generate/cache helper ────────────────────────────────────

async def _execute_with_cache(
    *,
    cache_key: str,
    generate_fn,
    build_response_fn,
    response_cls,
    ttl: int,
    log_prefix: str,
    request_id: str,
):
    """
    Reusable pattern: cache-read → generate → build response → cache-write.

    Parameters
    ----------
    cache_key       : Pre-computed SHA-256 key.
    generate_fn     : Async callable that invokes the LLM service.
    build_response_fn : Pure callable that turns a raw result dict into a response object.
    response_cls    : Pydantic response model class (used to rehydrate cached dicts).
    ttl             : Cache TTL in seconds.
    log_prefix      : Short identifier used in log messages (e.g. 'ContentGen').
    request_id      : UUID string for correlating log entries across a request lifecycle.
    """
    # 1. Cache read
    try:
        cached = cache_service.get_content(cache_key)
        if cached:
            logger.debug("[%s][%s] Cache hit", log_prefix, request_id)
            return response_cls(**cached)
    except Exception as exc:
        logger.warning("[%s][%s] Cache read error: %s", log_prefix, request_id, exc)

    # 2. Generate
    try:
        result = await generate_fn()
    except RateLimitError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))
    except LLMGenerationError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    except Exception as exc:
        logger.error(
            "[%s][%s] Unexpected generation error: %s",
            log_prefix, request_id, exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Content generation failed unexpectedly",
        )

    # 3. Build response
    response = build_response_fn(result)

    # 4. Cache write (non-fatal)
    try:
        cache_service.set_content(cache_key, response.model_dump(), ttl=ttl)
    except Exception as exc:
        logger.warning("[%s][%s] Cache write error: %s", log_prefix, request_id, exc)

    return response


# ── Product description endpoint ───────────────────────────────────────────

@router.post(
    "/generate",
    response_model=ContentGenerationResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate ecommerce product description and feature bullets",
)
async def generate_content(
    request: ContentGenerationRequest,
    _auth: None = Depends(verify_api_key),
):
    request_id = str(uuid.uuid4())
    product = request.product_data
    cache_key = _build_cache_key(request, namespace="generate")

    async def _generate():
        return  ContentGenerationService.generate(
            name=product.name,
            category=product.category,
            brand=product.brand,
            specifications=product.specifications,
            price=product.price,
            region=request.region,
            language=request.language,
            tone=request.tone,
            query=request.query,
        )

    def _build_response(result: dict) -> ContentGenerationResponse:
        desc = result["description"]
        return ContentGenerationResponse(
            product_name=product.name,
            language=request.language,
            region=request.region,
            tone=request.tone,
            description=GeneratedContent(
                content=desc,
                word_count=len(desc.strip().split()),
                char_count=len(desc),
            ),
            feature_bullets=result["feature_bullets"],
            provider=result.get("provider", "openai"),
        )

    return await _execute_with_cache(
        cache_key=cache_key,
        generate_fn=_generate,
        build_response_fn=_build_response,
        response_cls=ContentGenerationResponse,
        ttl=CONTENT_CACHE_TTL_SECONDS,
        log_prefix="ContentGen",
        request_id=request_id,
    )


# ── Social media post endpoint ─────────────────────────────────────────────

@router.post(
    "/social",
    response_model=SocialPostResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate a social media post with hashtags from product data",
)
async def generate_social_post(
    request: SocialPostRequest,
    _auth: None = Depends(verify_api_key),
):
    request_id = str(uuid.uuid4())
    product = request.product_data
    cache_key = _build_cache_key(request, namespace="social")

    async def _generate():
        return  ContentGenerationService.generate_social_post(
            name=product.name,
            category=product.category,
            brand=product.brand,
            specifications=product.specifications,
            price=product.price,
            region=request.region,
            language=request.language,
            tone=request.tone,
            query=request.query,
        )

    def _build_response(result: dict) -> SocialPostResponse:
        post_body = result["post_body"]
        return SocialPostResponse(
            product_name=product.name,
            language=request.language,
            region=request.region,
            tone=request.tone,
            post=SocialPostContent(
                post_body=post_body,
                hashtags=result["hashtags"],
                char_count=len(post_body),
            ),
            provider=result.get("provider", "openai"),
        )

    return await _execute_with_cache(
        cache_key=cache_key,
        generate_fn=_generate,
        build_response_fn=_build_response,
        response_cls=SocialPostResponse,
        ttl=CONTENT_CACHE_TTL_SECONDS,
        log_prefix="SocialGen",
        request_id=request_id,
    )