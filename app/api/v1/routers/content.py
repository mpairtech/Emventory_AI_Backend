from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/content", tags=["AI Content"])

CONTENT_CACHE_TTL_SECONDS = 3600  # 1 hour — applies to /generate, /social, /ad, /variants, and /improve


# ── Ad request/response schemas ────────────────────────────────────────────

class AdProductData(BaseModel):
    """Minimal product fields needed to generate an ad post."""
    name: str
    category: str
    brand: str
    specifications: list[str | dict] = Field(default_factory=list)


class AdGenerationRequest(BaseModel):
    product_data: AdProductData
    price: str = Field(..., description="Display price shown in the ad, e.g. '৳2,850'")
    shop_address: str = Field(..., description="Outlet address shown at the end of the ad")
    region: str = "BD"
    language: str = "English"
    tone: str = "enthusiastic"
    target_audience: str | None = Field(
        default=None,
        description="Audience persona e.g. 'students', 'gamers', 'professionals'",
    )


class AdContent(BaseModel):
    post_body: str
    hashtags: list[str]
    char_count: int


class AdGenerationResponse(BaseModel):
    product_name: str
    price: str
    shop_address: str
    language: str
    region: str
    tone: str
    post: AdContent
    provider: str


# ── Variants request/response schemas ──────────────────────────────────────

class VariantsProductData(BaseModel):
    """Product fields for the /variants endpoint."""
    name: str
    category: str | None = None
    brand: str | None = None
    specifications: list[str | dict] = Field(default_factory=list)
    price: float | None = None


class VariantsRequest(BaseModel):
    """
    Request body for POST /content/variants.

    Accepts a raw product blurb OR structured product_data.
    If blurb is provided it is used as the sole specification;
    product_data fields override extracted values when both are present.

    count: how many variants to generate (1–6, default 4).
    price and shop_address are top-level so they can be injected into
    every variant's closing line deterministically.
    """
    product_data: VariantsProductData
    price: str | None = Field(default=None, description="Display price, e.g. '৳2,850'")
    shop_address: str | None = Field(default=None, description="Outlet address for CTA line")
    region: str = "BD"
    language: str = "english"
    count: int = Field(default=4, ge=1, le=6, description="Number of variants to generate (1–6)")
    target_audience: str | None = Field(
        default=None,
        description="Audience persona e.g. 'students', 'gamers', 'professionals'",
    )


class VariantItem(BaseModel):
    label: str
    post_body: str
    hashtags: list[str]
    char_count: int


class VariantsResponse(BaseModel):
    product_name: str
    language: str
    region: str
    price: str | None
    shop_address: str | None
    variants: list[VariantItem]
    provider: str


# ── Improve description request/response schemas ───────────────────────────

class ImproveDescriptionRequest(BaseModel):
    raw_description: str = Field(
        ...,
        min_length=10,
        description="User-written product description to improve",
    )
    tone: str = Field(
        default="formal",
        description="One of: formal, casual, persuasive",
    )
    language: str = "english"
    region: str = "BD"
    length: str = Field(
        default="long",
        description=(
            "Output length preset: "
            "short (150–200 words), "
            "medium (300–350 words), "
            "long (450–500 words, default)"
        ),
    )

    @field_validator("tone")
    @classmethod
    def validate_tone(cls, v: str) -> str:
        allowed = {"formal", "casual", "persuasive"}
        if v.lower() not in allowed:
            raise ValueError(f"tone must be one of: {', '.join(sorted(allowed))}")
        return v.lower()

    @field_validator("length")
    @classmethod
    def validate_length(cls, v: str) -> str:
        allowed = {"short", "medium", "long"}
        if v.lower() not in allowed:
            raise ValueError(f"length must be one of: {', '.join(sorted(allowed))}")
        return v.lower()


class ImprovedDescriptionContent(BaseModel):
    content: str
    word_count: int
    char_count: int


class ImproveDescriptionResponse(BaseModel):
    tone: str
    language: str
    region: str
    length: str
    description: ImprovedDescriptionContent
    provider: str


# ── Cache key builders ─────────────────────────────────────────────────────

def _build_cache_key(request: ContentGenerationRequest | SocialPostRequest, namespace: str) -> str:
    product = request.product_data
    specs   = product.specifications

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
            "price":          getattr(product, "price", None),
            "query":          request.query,
            "region":         request.region,
            "language":       request.language,
            "tone":           request.tone,
            "shop_address":   getattr(request, "shop_address", None),
            "namespace":      namespace,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_ad_cache_key(request: AdGenerationRequest) -> str:
    specs = request.product_data.specifications
    if specs and isinstance(specs[0], dict):
        sorted_specs = sorted(specs, key=lambda x: x["key"])
    else:
        sorted_specs = sorted(specs) if specs else []

    payload = json.dumps(
        {
            "namespace":      "ad",
            "name":           request.product_data.name,
            "category":       request.product_data.category,
            "brand":          request.product_data.brand,
            "specifications": sorted_specs,
            "price":          request.price,
            "shop_address":   request.shop_address,
            "region":         request.region,
            "language":       request.language,
            "tone":           request.tone,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_variants_cache_key(request: VariantsRequest) -> str:
    """
    Deterministic cache key for /variants.
    count is included so changing the number of variants busts the cache.
    """
    specs = request.product_data.specifications
    if specs and isinstance(specs[0], dict):
        sorted_specs = sorted(specs, key=lambda x: x["key"])
    else:
        sorted_specs = sorted(specs) if specs else []

    payload = json.dumps(
        {
            "namespace":      "variants",
            "name":           request.product_data.name,
            "category":       request.product_data.category,
            "brand":          request.product_data.brand,
            "specifications": sorted_specs,
            "price":          request.price,
            "shop_address":   request.shop_address,
            "region":         request.region,
            "language":       request.language,
            "count":          request.count,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_improve_cache_key(request: ImproveDescriptionRequest) -> str:
    """
    Deterministic cache key for /improve.
    Keyed on raw_description + tone + language + region + length.
    length is included so short/medium/long requests never share a cache entry.
    """
    payload = json.dumps(
        {
            "namespace":       "improve",
            "raw_description": request.raw_description,
            "tone":            request.tone,
            "language":        request.language,
            "region":          request.region,
            "length":          request.length,
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
    product    = request.product_data
    cache_key  = _build_cache_key(request, namespace="generate")

    async def _generate():
        return await asyncio.to_thread(
            ContentGenerationService.generate,
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
    product    = request.product_data
    cache_key  = _build_cache_key(request, namespace="social")

    async def _generate():
        return await asyncio.to_thread(
            ContentGenerationService.generate_social_post,
            name=product.name,
            category=product.category,
            brand=product.brand,
            specifications=product.specifications,
            price=request.price,
            region=request.region,
            language=request.language,
            tone=request.tone,
            query=request.query,
            shop_address=request.shop_address,
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

    response = await _execute_with_cache(
        cache_key=cache_key,
        generate_fn=_generate,
        build_response_fn=_build_response,
        response_cls=SocialPostResponse,
        ttl=CONTENT_CACHE_TTL_SECONDS,
        log_prefix="SocialGen",
        request_id=request_id,
    )

    # Guaranteed price + address injection on every response (cache hits included).
    if request.shop_address:
        raw_body  = response.post.post_body.rstrip()
        lines     = raw_body.split("\n")
        last_line = lines[-1].strip().lower()
        cta_triggers = ("visit our outlet", "order online", "fastest delivery")
        if any(t in last_line for t in cta_triggers):
            raw_body = "\n".join(lines[:-1]).rstrip()

        cta_line = f"Visit our outlet at {request.shop_address} or order online for the fastest delivery."

        if request.price:
            price_line = f"{product.name} — Price: {request.price}/-"
            final_body = f"{raw_body}\n\n{price_line}\n{cta_line}"
        else:
            final_body = f"{raw_body}\n\n{cta_line}"

        response.post.post_body  = final_body
        response.post.char_count = len(final_body)

    return response


# ── Variants endpoint ──────────────────────────────────────────────────────

@router.post(
    "/variants",
    response_model=VariantsResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate multiple distinct social post variants for a product in one call",
)
async def generate_variants(
    request: VariantsRequest,
    _auth: None = Depends(verify_api_key),
):
    """
    Generate `count` (1–6) distinctly styled social media post variants in a
    single OpenAI call.

    Each variant uses a different writing style:
      1. Hype Drop         — launch-announcement energy
      2. Storytelling      — pain-point → solution narrative
      3. Feature Spotlight — one hero spec, everything supports it
      4. Value Deal        — price-to-performance, FOMO-driven
      5. Lifestyle Fit     — daily-use scenarios, aspirational
      6. Minimalist        — short, punchy, no fluff

    Price and shop_address (when provided) are guaranteed to appear in every
    variant's closing line — applied post-generation in the service layer so
    cache hits are also correctly injected.
    """
    request_id = str(uuid.uuid4())
    product    = request.product_data
    cache_key  = _build_variants_cache_key(request)

    logger.info(
        "[VariantsGen][%s] product=%r count=%d language=%s",
        request_id, product.name, request.count, request.language,
    )

    async def _generate():
        specs = product.specifications
        flat_specs = (
            [f"{s['key']}: {s['value']}" if isinstance(s, dict) else str(s) for s in specs]
            if specs else []
        )
        return await asyncio.to_thread(
            ContentGenerationService.generate_social_variants,
            name=product.name,
            category=product.category,
            brand=product.brand,
            specifications=flat_specs,
            price=request.price,
            region=request.region,
            language=request.language,
            shop_address=request.shop_address,
            count=request.count,
        )

    def _build_response(variants: list[dict]) -> VariantsResponse:
        return VariantsResponse(
            product_name=product.name,
            language=request.language,
            region=request.region,
            price=request.price,
            shop_address=request.shop_address,
            variants=[
                VariantItem(
                    label=v["label"],
                    post_body=v["post_body"],
                    hashtags=v["hashtags"],
                    char_count=len(v["post_body"]),
                )
                for v in variants
            ],
            provider="openai",
        )

    return await _execute_with_cache(
        cache_key=cache_key,
        generate_fn=_generate,
        build_response_fn=_build_response,
        response_cls=VariantsResponse,
        ttl=CONTENT_CACHE_TTL_SECONDS,
        log_prefix="VariantsGen",
        request_id=request_id,
    )


# ── Ad copy endpoint ───────────────────────────────────────────────────────

@router.post(
    "/ad",
    response_model=AdGenerationResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate a social media ad post with price and shop address",
)
async def generate_ad(
    request: AdGenerationRequest,
    _auth: None = Depends(verify_api_key),
):
    request_id = str(uuid.uuid4())
    product    = request.product_data
    cache_key  = _build_ad_cache_key(request)

    logger.info(
        "[AdGen][%s] product=%r price=%r tone=%s language=%s",
        request_id, product.name, request.price, request.tone, request.language,
    )

    async def _generate():
        return await asyncio.to_thread(
            ContentGenerationService.generate_ad,
            name=product.name,
            category=product.category,
            brand=product.brand,
            specifications=product.specifications,
            price=request.price,
            shop_address=request.shop_address,
            region=request.region,
            language=request.language,
            tone=request.tone,
        )

    def _build_response(result: dict) -> AdGenerationResponse:
        post_body = result["post_body"]
        return AdGenerationResponse(
            product_name=product.name,
            price=request.price,
            shop_address=request.shop_address,
            language=request.language,
            region=request.region,
            tone=request.tone,
            post=AdContent(
                post_body=post_body,
                hashtags=result["hashtags"],
                char_count=len(post_body),
            ),
            provider=result.get("provider", "openai"),
        )

    response = await _execute_with_cache(
        cache_key=cache_key,
        generate_fn=_generate,
        build_response_fn=_build_response,
        response_cls=AdGenerationResponse,
        ttl=CONTENT_CACHE_TTL_SECONDS,
        log_prefix="AdGen",
        request_id=request_id,
    )

    # Guaranteed price + address injection on every response (cache hits included).
    raw_body  = response.post.post_body.rstrip()
    lines     = raw_body.split("\n")
    last_line = lines[-1].strip().lower()
    cta_triggers = ("visit our outlet", "order online", "fastest delivery")
    if any(t in last_line for t in cta_triggers):
        raw_body = "\n".join(lines[:-1]).rstrip()

    price_line = f"{product.name} \u2014 Price: {request.price}/-"
    cta_line   = f"Visit our outlet at {request.shop_address} or order online for the fastest delivery."
    final_body = f"{raw_body}\n\n{price_line}\n{cta_line}"

    response.post.post_body  = final_body
    response.post.char_count = len(final_body)
    return response


# ── Improve description endpoint ───────────────────────────────────────────

@router.post(
    "/improve",
    response_model=ImproveDescriptionResponse,
    status_code=status.HTTP_200_OK,
    summary="Improve a user-written product description with tone and length adjustment",
)
async def improve_description(
    request: ImproveDescriptionRequest,
    _auth: None = Depends(verify_api_key),
):
    """
    Accepts a raw product description typed by the user and rewrites it into
    polished, tone-adjusted copy (formal / casual / persuasive).

    Length preset controls output word count:
      - short:  150–200 words  (1–2 sections)
      - medium: 300–350 words  (2–3 sections)
      - long:   450–500 words  (4–6 sections, default)

    All product facts, specs, prices, and claims are preserved exactly.
    """
    request_id = str(uuid.uuid4())
    cache_key  = _build_improve_cache_key(request)

    logger.info(
        "[ImproveDesc][%s] tone=%s language=%s length=%s chars=%d",
        request_id, request.tone, request.language, request.length, len(request.raw_description),
    )

    async def _generate():
        return await asyncio.to_thread(
            ContentGenerationService.improve_description,
            raw_description=request.raw_description,
            tone=request.tone,
            language=request.language,
            region=request.region,
            length=request.length,
        )

    def _build_response(result: dict) -> ImproveDescriptionResponse:
        desc = result["improved_description"]
        return ImproveDescriptionResponse(
            tone=request.tone,
            language=request.language,
            region=request.region,
            length=request.length,
            description=ImprovedDescriptionContent(
                content=desc,
                word_count=len(desc.strip().split()),
                char_count=len(desc),
            ),
            provider="openai",
        )

    return await _execute_with_cache(
        cache_key=cache_key,
        generate_fn=_generate,
        build_response_fn=_build_response,
        response_cls=ImproveDescriptionResponse,
        ttl=CONTENT_CACHE_TTL_SECONDS,
        log_prefix="ImproveDesc",
        request_id=request_id,
    )