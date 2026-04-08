from __future__ import annotations

import json
import logging
from typing import Optional

from openai import OpenAI

from app.core.config import settings
from app.core.exceptions import LLMGenerationError, RateLimitError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ELECTRONIC_KEYWORDS = {
    "phone", "smartphone", "laptop", "tablet", "computer", "monitor",
    "television", "tv", "camera", "headphone", "speaker", "charger",
    "router", "electronics", "gadget", "processor", "gpu", "cpu",
    "ssd", "hard drive", "keyboard", "mouse", "printer", "scanner",
    "smartwatch", "wearable", "drone", "projector", "amplifier",
    "microphone", "earphone", "earbuds", "powerbank", "power bank",
    "mobile", "display", "graphics card", "motherboard", "ram",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_electronic(category: Optional[str], name: Optional[str] = None) -> bool:
    """Check if the product is electronics based on category or product name."""
    text = f"{category or ''} {name or ''}".lower()
    return any(kw in text for kw in ELECTRONIC_KEYWORDS)


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


def _build_system_prompt(
    tone: str,
    language: str,
    region: str,
    category: Optional[str] = None,
    name: Optional[str] = None,
) -> str:
    tone_guidance = {
        "formal":     "Use professional, informative language suitable for B2B or premium ecommerce product listings.",
        "casual":     "Use clear, friendly language suitable for consumer ecommerce product pages.",
        "persuasive": "Use benefit-driven, value-focused language that encourages purchase decisions on ecommerce product pages.",
    }

    word_count_rule = (
        "Descriptions must be strictly 300-350 words."
        if _is_electronic(category, name) else
        "Descriptions must be strictly 200-250 words."
    )

    return (
        f"You are an expert ecommerce product content writer specialising in product listing pages. "
        f"Write all output in {language.upper()} language, optimised for the {region} market. "
        f"Your content is strictly for ecommerce product listing pages — structured product titles and spec-based descriptions. "
        f"Do NOT write social media posts, advertisements, hashtags, slogans, or any marketing campaign content. "
        f"Do NOT use phrases like 'Follow us', 'Tag a friend', 'Limited time offer', or any social or ad copy. "
        f"{word_count_rule} Count carefully before responding. Do not go under the minimum. "
        f"Always follow the exact 5-section structure: title, category context, product details, use cases, buy closing paragraph. "
        f"Adapt tone and structure naturally to the product type and category. "
        f"Tone: {tone_guidance.get(tone, 'professional and informative')} "
        f"Return ONLY valid JSON — no markdown, no code fences, no preamble."
    )


def _build_social_system_prompt(tone: str, language: str, region: str) -> str:
    tone_guidance = {
        "formal":     "Write in a professional, brand-authoritative voice with controlled excitement — suitable for corporate Facebook pages.",
        "casual":     "Write in a friendly, hype-driven conversational voice with energy — suitable for Instagram and Facebook consumer audiences.",
        "persuasive": "Write in a high-energy, benefit-driven voice that creates urgency, excitement, and strong purchase intent.",
    }
    return (
        f"You are a high-energy social media copywriter specialising in ecommerce product promotions for Facebook and Instagram. "
        f"Write all output in {language.upper()} language, optimised for the {region} market. "
        f"Your job is to write scroll-stopping, hype-driven captions in flowing conversational paragraphs — NO bullet points, NO section headers. "
        f"Use markdown bold (**text**) only where explicitly instructed — do not bold randomly. "
        f"Tone: {tone_guidance.get(tone, 'hype-driven and exciting')} "
        f"NEVER use hollow filler phrases like 'redefining excellence', 'designed for your lifestyle', 'take it to the next level', or 'perfect for everyone'. "
        f"NEVER write generic ad copy — every sentence must reference the actual product data provided. "
        f"Return ONLY valid JSON — no markdown, no code fences, no preamble."
    )


def _build_user_prompt(
    product_summary: str,
    query: Optional[str],
    category: Optional[str] = None,
    name: Optional[str] = None,
) -> str:
    context_hint = f'\nContext hint: "{query}"' if query else ""
    word_count = "300-350 words" if _is_electronic(category, name) else "200-250 words"

    return f"""Generate ecommerce product listing page content for this product:

{product_summary}{context_hint}

Return a single JSON object with exactly these keys:
{{
  "description": "<full ecommerce product page description — follow the format rules below>",
  "feature_bullets": ["<bullet 1>", "<bullet 2>", "<bullet 3>", "<bullet 4>", "<bullet 5>"]
}}

Description format rules:

Follow this EXACT 5-section structure:

1. PRODUCT TITLE (Line 1)
   - Write the full product name as a standalone title line

2. CATEGORY CONTEXT (1 paragraph)
   - Describe what this TYPE of product is and why people buy it
   - Write about the product category broadly — not this specific product
   - Example: for wall art, describe how wall art transforms living spaces and why it matters in home decor
   - Example: for a smartphone, describe how smartphones have become essential tools for modern life
   - Example: for furniture, describe how furniture shapes the comfort and personality of a living space
   - This paragraph sets the context for why the product category exists and why buyers care

3. PRODUCT DETAILS (2-3 paragraphs)
   - Describe this specific product: design, material, build quality, size/variants, features
   - Choose section focus naturally based on what the product actually is
   - For decor products: focus on aesthetics, finish, dimensions, craftsmanship
   - For electronics: focus on performance, display, battery, connectivity
   - For clothing: focus on fit, fabric, style options, care
   - For furniture: focus on material, dimensions, assembly, finish
   - For industrial/safety products: focus on material, protection rating, compliance, durability
   - Use ONLY the facts provided — do NOT invent specs, numbers, or features not in the product data

4. USE CASES (1 paragraph)
   - Describe real-world scenarios where this product fits naturally
   - Mention specific rooms, environments, occasions, or user types
   - Example for decor: "Ideal for living rooms, bedrooms, offices, or as a thoughtful gift for housewarmings..."
   - Example for electronics: "Perfect for students, remote workers, content creators, or everyday users..."
   - Example for industrial: "Suitable for factory workers, construction sites, warehouse staff, or industrial technicians..."
   - Make it feel natural and relatable to the target buyer

5. BUY CLOSING PARAGRAPH (1 paragraph)
   - Start with "Buy [product name]"
   - Mention availability (in stock, multiple sizes/variants available, etc.)
   - Mention warranty only if provided in the product data — if not specified, omit warranty mention entirely

General rules:
- Total length: {word_count}. Do not go under the minimum. Count carefully before responding.
- Use ONLY the facts provided. Do NOT invent specs, numbers, or features
- No hashtags, no social media language, no slogans, no promotional ad copy
- Write exactly as a product description on a professional ecommerce website

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
   - Use this EXACT format and wrap the ENTIRE line in markdown bold:
     "Translate this pattern naturally into the output language: 'Want both [benefit 1] and [benefit 2] at the same time? Then the [Product Name] is now available at the best price at [Brand Name].'"
   - [benefit 1] and [benefit 2] must come from actual product specs (e.g. "performance and style", "speed and battery life", "camera quality and smooth display")
   - [Product Name] = product name from the data
   - [Brand Name] = brand from the data — if no brand provided, omit "at [Brand Name]"
   - Do NOT use any bold markdown on this line
   - Separate from next paragraph with a blank line (\\n\\n)

2. BODY PARAGRAPHS (2-3 short paragraphs):
   - Write in flowing conversational sentences — NO bullet points, NO section headers whatsoever
   - FIRST body paragraph: plain text, no bold
   - SECOND and THIRD paragraphs: plain text, no bold
   - Separate each paragraph with a blank line (\\n\\n)
   - Each paragraph focuses on one angle: performance, camera, display, battery, build, etc.
   - Every sentence must reference actual product specs from the data provided
   - Write benefit-first: what the user GAINS, not just the spec name
   - Keep each paragraph to 2-3 sentences maximum
   - Use casual, hype-driven language that feels natural on Facebook/Instagram
   - NEVER use hollow filler phrases like "redefining excellence" or "designed for your lifestyle"
   - Do NOT use ✅, 📋, •, or any bullet symbols anywhere

3. PRICE + CTA LINE (1 line):
   - Format: "[Product Name] ([storage/variant if available]) — Price: [price if provided]/-"
   - Follow immediately with the equivalent of "Visit our outlet or order online for the fastest delivery." translated naturally into the output language.
   - If no price is provided in the product data, omit the price portion and just write the CTA line
   - No bold on this line

STRICT RULES:
- DO NOT use bullet points anywhere in post_body
- DO NOT use section headers like "Key Highlights" or "Specs at a Glance"
- DO NOT bold anything except the hook line and the first body paragraph
- DO NOT include hashtags inside post_body — they go in the hashtags list only
- Separate every paragraph with \\n\\n (blank line)
- Total post_body length: 100-160 words

hashtags rules:
- Between 5 and 10 hashtags
- Each is a single word or compound word, no spaces (e.g. "TechDeals", "Samsung", "Smartphone")
- Include: brand name, product name/model, product category, 1-2 generic tech tags, 1 regional/market tag
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
        system_prompt   = _build_system_prompt(tone, language, region, category, name)
        user_prompt     = _build_user_prompt(product_summary, query, category, name)

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