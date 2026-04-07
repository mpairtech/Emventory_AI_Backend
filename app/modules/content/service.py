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


def _build_social_system_prompt(tone: str, language: str, region: str) -> str:
    tone_guidance = {
        "formal":     "Write in a professional, brand-authoritative voice with controlled excitement — suitable for corporate Facebook pages.",
        "casual":     "Write in a friendly, hype-driven conversational voice with energy and emojis — suitable for Instagram and Facebook consumer audiences.",
        "persuasive": "Write in a high-energy, benefit-driven voice that creates urgency, excitement, and strong purchase intent.",
    }
    return (
        f"You are a high-energy social media copywriter specialising in ecommerce product promotions for Facebook and Instagram. "
        f"Write all output in {language.upper()} language, optimised for the {region} market. "
        f"Your job is to write scroll-stopping, hype-driven captions that make people want to buy immediately. "
        f"Tone: {tone_guidance.get(tone, 'hype-driven and exciting')} "
        f"NEVER use hollow filler phrases like 'redefining excellence', 'designed for your lifestyle', 'take it to the next level', or 'perfect for everyone'. "
        f"NEVER write generic ad copy — every sentence must reference the actual product data provided. "
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


def _build_social_user_prompt(product_summary: str, query: Optional[str]) -> str:
    context_hint = f'\nContext hint: "{query}"' if query else ""
    return f"""Generate a Facebook and Instagram product promotion caption for this product:

{product_summary}{context_hint}

Return a single JSON object with exactly these keys:
{{
  "post_body": "<the full caption — follow ALL rules below>",
  "hashtags": ["hashtag1", "hashtag2", "hashtag3", "hashtag4", "hashtag5"]
}}

post_body rules — follow this EXACT structure:

1. HOOK LINE (1 line):
   - Start with an emoji (🔥 or ⚡ or 🚨)
   - Address a real pain point or desire the product solves (e.g. bad camera, slow performance, short battery)
   - Immediately position this product as the fix
   - Example pattern: "🔥 Tired of [problem]? Meet [Product Name] — [punchy solution in bold using **text**]"

2. BOLD POWER STATEMENT (1 line):
   - Bold the product name and one punchy benefit statement
   - Format: **[Product Name] — [One punchy benefit statement]**

3. KEY HIGHLIGHTS (bullet list):
   - Prefix: "✅ Key Highlights:"
   - 3–4 bullet points using • symbol
   - Each bullet = benefit-driven (what the user GAINS), not just spec names
   - Good: "• Capture pro-level shots even in low light"
   - Bad: "• 50MP camera"

4. SPECS AT A GLANCE (bullet list):
   - Prefix: "📋 Specs at a Glance:"
   - 3–4 bullet points using • symbol
   - Factual, concise spec values only (e.g. "• RAM: 12GB", "• Display: 6.7″ AMOLED 120Hz")
   - Use ONLY specs from the product data — do NOT invent values

5. ADDRESS BLOCK:
   - If address data is available: "📍 Find Us At:\\n[address]"
   - If address is missing: "📍 Visit our store for details"

6. CONTACT BLOCK:
   - If contact data is available: "📞 Contact Us:\\n[phone or email]"
   - If contact is missing: omit this block entirely

DO NOT include hashtags inside post_body — they go in the hashtags list only.
DO NOT use hollow filler phrases like "redefining excellence" or "designed for your lifestyle".
Total post_body length: 100–180 words.

hashtags rules:
- Between 5 and 10 hashtags
- Each is a single word or compound word, no spaces (e.g. "TechDeals", "Samsung", "Smartphone")
- Include: brand name, product name/model, product category, 1–2 generic tech tags, 1 regional/market tag
- No # symbol in the list — just the word

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
        """Generate ecommerce product listing page content via OpenAI."""
        product_summary = _build_product_summary(name, category, brand, specifications, price)
        system_prompt   = _build_system_prompt(tone, language, region)
        user_prompt     = _build_user_prompt(product_summary, query)

        raw = ContentGenerationService._call_openai(system_prompt, user_prompt, name, "ContentGen")
        return ContentGenerationService._parse_and_validate(raw, {"description", "feature_bullets"})

    @staticmethod
    def generate_social_post(
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
        """Generate a social media post with hashtags via OpenAI."""
        product_summary = _build_product_summary(name, category, brand, specifications, price)
        system_prompt   = _build_social_system_prompt(tone, language, region)
        user_prompt     = _build_social_user_prompt(product_summary, query)

        raw = ContentGenerationService._call_openai(system_prompt, user_prompt, name, "SocialGen")

        result = ContentGenerationService._parse_and_validate(raw, {"post_body", "hashtags"})

        if not isinstance(result.get("hashtags"), list):
            raise LLMGenerationError("hashtags must be a list")

        return {
            "post_body": str(result["post_body"]).strip(),
            "hashtags":  [str(h).strip().lstrip("#") for h in result["hashtags"] if h],
        }

    # ── Shared OpenAI call ─────────────────────────────────────────────────

    @staticmethod
    def _call_openai(system_prompt: str, user_prompt: str, name: str, log_tag: str) -> str:
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

            logger.info("[%s] Generated for '%s'", log_tag, name)
            return raw

        except LLMGenerationError:
            raise
        except Exception as e:
            err_type = type(e).__name__
            err_msg  = str(e).lower()

            if "rate limit" in err_msg or "quota" in err_msg or "429" in err_msg or "RateLimitError" in err_type:
                logger.warning("[%s] Rate limit hit: %s", log_tag, e)
                raise RateLimitError(f"OpenAI rate limit exceeded: {e}")
            if "auth" in err_msg or "api key" in err_msg or "401" in err_msg:
                raise LLMGenerationError(f"OpenAI authentication error: {e}")
            if "connection" in err_msg or "timeout" in err_msg:
                raise LLMGenerationError(f"OpenAI network error: {e}")

            raise LLMGenerationError(f"Generation failed: {e}")

    # ── Shared parse & validate ────────────────────────────────────────────

    @staticmethod
    def _parse_and_validate(raw: str, required_keys: set) -> dict:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error("[ContentGen] JSON parse error: %s | raw: %s", e, raw[:300])
            raise LLMGenerationError(f"OpenAI returned invalid JSON: {e}")

        missing = required_keys - set(data.keys())
        if missing:
            raise LLMGenerationError(f"OpenAI response missing keys: {missing}")

        return data