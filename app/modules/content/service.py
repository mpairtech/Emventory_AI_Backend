from __future__ import annotations

import json
import logging
from typing import Optional

from openai import OpenAI

from app.core.config import settings
from app.core.exceptions import LLMGenerationError, RateLimitError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_client() -> OpenAI:
    if not settings.OPENAI_API_KEY:
        raise LLMGenerationError("OPENAI_API_KEY is not configured")
    try:
        return OpenAI(api_key=settings.OPENAI_API_KEY)
    except Exception as e:
        raise LLMGenerationError(f"Failed to initialise OpenAI client: {e}")


def _build_product_summary(
    name: str,
    category: Optional[str],
    brand: Optional[str],
    specifications: list[str],
    price: Optional[float],
) -> str:
    lines = [f"Product Name: {name}"]
    if brand:
        lines.append(f"Brand: {brand}")
    if category:
        lines.append(f"Category: {category}")
    if price is not None:
        lines.append(f"Price: {price}")
    if specifications:
        lines.append("Specifications:\n" + "\n".join(f"  - {s}" for s in specifications))
    return "\n".join(lines)


def _build_system_prompt(tone: str, language: str, region: str) -> str:
    tone_guidance = {
        "formal":     "Use professional, informative language suitable for B2B or premium ecommerce product listings.",
        "casual":     "Use clear, friendly language suitable for consumer ecommerce product pages.",
        "persuasive": "Use benefit-driven, value-focused language that encourages purchase decisions on ecommerce product pages.",
    }
    return (
        f"You are an expert ecommerce product content writer specialising in product listing pages. "
        f"Write all output in {language.upper()} language, optimised for the {region} market. "
        f"Your content is strictly for ecommerce product listing pages — structured product titles and spec-based descriptions. "
        f"Do NOT write social media posts, advertisements, hashtags, slogans, or any marketing campaign content. "
        f"Do NOT use phrases like 'Follow us', 'Tag a friend', 'Limited time offer', or any social or ad copy. "
        f"Tone: {tone_guidance.get(tone, 'professional and informative')} "
        f"Return ONLY valid JSON — no markdown, no code fences, no preamble."
    )


def _build_user_prompt(product_summary: str, query: Optional[str]) -> str:
    context_hint = f'\nContext hint: "{query}"' if query else ""
    return f"""Generate ecommerce product listing page content for this product:

{product_summary}{context_hint}

Return a single JSON object with exactly these keys:
{{
  "description": "<full ecommerce product page description — follow the format rules below>",
  "feature_bullets": ["<bullet 1>", "<bullet 2>", "<bullet 3>", "<bullet 4>", "<bullet 5>"]
}}

Description format rules:
- Line 1: Full product name as a standalone title
- Then write 2-4 sections, each with a short heading (e.g. "Performance", "Display and Design", "Connectivity and Battery")
- Each section is a dense factual paragraph covering the relevant specs provided
- Final paragraph: "Buy [product name]" — mention availability and warranty if known
- Total length: 150-300 words
- Use ONLY the facts provided. Do NOT invent specs, numbers, or features not in the product data
- No hashtags, no social media language, no slogans, no promotional ad copy
- Write exactly as a product description on an ecommerce website

feature_bullets rules:
- Exactly 5 bullets
- Each bullet is a factual spec or key benefit, under 15 words
- No marketing fluff, no hashtags

Return ONLY the JSON object. Nothing else."""


# ---------------------------------------------------------------------------
# Public service
# ---------------------------------------------------------------------------

class ContentGenerationService:

    @staticmethod
    def generate(
        name: str,
        category: Optional[str],
        brand: Optional[str],
        specifications: list[str],
        price: Optional[float],
        region: str,
        language: str,
        tone: str,
        query: Optional[str] = None,
    ) -> dict:
        """
        Generate ecommerce product listing page content via OpenAI.

        Returns dict with keys: description, feature_bullets
        """
        product_summary = _build_product_summary(name, category, brand, specifications, price)
        system_prompt   = _build_system_prompt(tone, language, region)
        user_prompt     = _build_user_prompt(product_summary, query)

        max_tokens = 1500 if "mini" in settings.OPENAI_MODEL.lower() else 2048

        try:
            client   = _get_client()
            response = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                temperature=0.3,
                top_p=0.9,
                frequency_penalty=0.1,
                presence_penalty=0.0,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )

            if not response.choices:
                raise LLMGenerationError("OpenAI returned empty choices")

            raw = response.choices[0].message.content
            if not raw:
                raise LLMGenerationError("OpenAI returned empty content")

            logger.info(
                "[ContentGen] Generated for '%s' | tone=%s | lang=%s | region=%s",
                name, tone, language, region,
            )
            return ContentGenerationService._parse_and_validate(raw)

        except LLMGenerationError:
            raise
        except Exception as e:
            err_type = type(e).__name__
            err_msg  = str(e).lower()

            if "rate limit" in err_msg or "quota" in err_msg or "429" in err_msg or "RateLimitError" in err_type:
                logger.warning("[ContentGen] Rate limit hit: %s", e)
                raise RateLimitError(f"OpenAI rate limit exceeded: {e}")

            if "auth" in err_msg or "api key" in err_msg or "401" in err_msg:
                raise LLMGenerationError(f"OpenAI authentication error: {e}")

            if "connection" in err_msg or "timeout" in err_msg:
                raise LLMGenerationError(f"OpenAI network error: {e}")

            raise LLMGenerationError(f"Content generation failed: {e}")

    @staticmethod
    def _parse_and_validate(raw: str) -> dict:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error("[ContentGen] JSON parse error: %s | raw: %s", e, raw[:300])
            raise LLMGenerationError(f"OpenAI returned invalid JSON: {e}")

        missing = {"description", "feature_bullets"} - set(data.keys())
        if missing:
            raise LLMGenerationError(f"OpenAI response missing keys: {missing}")

        if not isinstance(data.get("feature_bullets"), list):
            raise LLMGenerationError("feature_bullets must be a list")

        return {
            "description":     str(data["description"]).strip(),
            "feature_bullets": [str(b).strip() for b in data["feature_bullets"] if b],
        }