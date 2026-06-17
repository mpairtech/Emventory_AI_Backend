from __future__ import annotations

import json
import logging
from typing import Optional, Union

from openai import OpenAI, RateLimitError as OpenAIRateLimitError, AuthenticationError, APIConnectionError

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

# Max tokens for description/improve generation — intentionally capped below
# the model's output limit; descriptions longer than ~500 words are rarely
# needed and keeping this low reduces latency and cost.
DESCRIPTION_MAX_TOKENS = 2048

# ---------------------------------------------------------------------------
# Length preset definitions
# ---------------------------------------------------------------------------

# Maps the user-facing length preset to a (min_words, max_words) tuple.
# Used by /improve to control output length via both the system prompt and
# the user prompt so the model gets two consistent signals.
DESCRIPTION_LENGTH_PRESETS: dict[str, tuple[int, int]] = {
    "short":  (150, 200),
    "medium": (300, 350),
    "long":   (450, 500),  # default — matches legacy behaviour
}

# ---------------------------------------------------------------------------
# Variant style definitions
# ---------------------------------------------------------------------------

VARIANT_STYLES = [
    {
        "label":       "Hype Drop",
        "description": (
            "High-energy launch-announcement style. Open with a punchy one-liner drop, "
            "build excitement through specs, close with urgency. "
            "Feel: streetwear brand announcing a product drop."
        ),
    },
    {
        "label":       "Storytelling",
        "description": (
            "Open with a relatable customer pain point or scenario, then introduce the product "
            "as the solution. Let the specs emerge through the story. "
            "Feel: a friend recommending something they personally use."
        ),
    },
    {
        "label":       "Feature Spotlight",
        "description": (
            "Pick the single most impressive spec and lead the entire post with it. "
            "Every sentence supports or reinforces that one hero feature. "
            "Feel: a tech reviewer doing a focused teardown."
        ),
    },
    {
        "label":       "Value Deal",
        "description": (
            "Lead with price-to-performance. Make the reader feel they'd be missing out "
            "if they don't grab this. Emphasise what you get for the money. "
            "Feel: a flash-sale announcement."
        ),
    },
    {
        "label":       "Lifestyle Fit",
        "description": (
            "Paint a picture of the customer's life with this product in it. "
            "Focus on daily-use scenarios, portability, and how it fits naturally into routines. "
            "Feel: a aspirational Instagram caption."
        ),
    },
    {
        "label":       "Minimalist",
        "description": (
            "Short. Punchy. No fluff. Every sentence earns its place. "
            "2-3 tight paragraphs, each one a knockout line. "
            "Feel: Apple product page copy."
        ),
    },
]


# ---------------------------------------------------------------------------
# Lazy singleton
# ---------------------------------------------------------------------------

_openai_client: OpenAI | None = None

def _get_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        if not settings.OPENAI_API_KEY:
            raise LLMGenerationError("OPENAI_API_KEY is not configured")
        try:
            _openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
        except Exception as e:
            raise LLMGenerationError(f"Failed to initialise OpenAI client: {e}")
    return _openai_client


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_electronic(category: Optional[str], name: Optional[str] = None) -> bool:
    """Check if the product is electronics based on category or product name."""
    text = f"{category or ''} {name or ''}".lower()
    return any(kw in text for kw in ELECTRONIC_KEYWORDS)


def _build_product_summary(
    name: str,
    category: Optional[str],
    brand: Optional[str],
    specifications: list[str],
    price: Union[str, float, None],
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
        "formal":     "Use professional, authoritative language suitable for premium or B2B product pages.",
        "casual":     "Use friendly, approachable language suitable for everyday consumer products.",
        "persuasive": "Use benefit-driven, value-focused language that builds confidence and encourages purchase.",
    }

    return (
        f"You are an expert ecommerce product content writer specialising in SEO-optimised product description pages. "
        f"Write all output in {language.upper()} language, optimised for the {region} market. "
        f"Your descriptions must read like a professional buying guide — structured with dynamic section headers, "
        f"benefit-first storytelling paragraphs, and real-world use case examples woven naturally into the body. "
        f"Adapt section headers dynamically to suit the product type and category — do NOT use fixed generic headers. "
        f"For electronics: use headers like chip/performance, display, battery, design, memory/storage. "
        f"For clothing: use headers like fabric/material, fit/style, occasions, care. "
        f"For furniture: use headers like build/material, dimensions/assembly, room fit, finish. "
        f"For decor: use headers like aesthetics, craftsmanship, placement, occasions. "
        f"For industrial/safety products: use headers like protection, durability, compliance, applications. "
        f"Every paragraph must explain real-world benefits — what the user gains — not just list specs. "
        f"Weave use cases and examples naturally inside each section paragraph. "
        f"Do NOT write a separate 'Use Cases' section — integrate examples into every section. "
        f"Total description length: 450-500 words. Count carefully. Do not go under 450 words. "
        f"Tone: {tone_guidance.get(tone, 'professional and benefit-driven')} "
        f"Use ONLY facts from the product data provided. Do NOT invent specs, features, or claims. "
        f"Return ONLY valid JSON — no markdown, no code fences, no preamble."
    )


def _build_user_prompt(
    product_summary: str,
    query: Optional[str],
    category: Optional[str] = None,
    name: Optional[str] = None,
) -> str:
    context_hint = f'\nContext hint: "{query}"' if query else ""

    return f"""Generate a professional ecommerce product description page for this product:

{product_summary}{context_hint}

Return a single JSON object with exactly these keys:
{{
  "description": "<full product description — follow ALL rules below>",
  "feature_bullets": ["<bullet 1>", "<bullet 2>", "<bullet 3>", "<bullet 4>", "<bullet 5>"]
}}

Description rules:

STRUCTURE:
- Line 1: Full product name as a standalone title (no label, just the name)
-  NO blank line after title — the first section header follows immediately after the title
- Then 4-6 sections, each with:
    - A bold section header on its own line (e.g. **Premium Design Built for Daily Life**)
    - Blank line after header
    - 1-2 paragraphs of benefit-first storytelling content
    - Blank line between paragraphs and after each section

SECTION HEADER RULES:
- Choose headers dynamically based on what the product actually is
- Headers must be specific to the product — NOT generic like "Key Features" or "Product Details"
- For electronics: performance/chip, display, memory/storage, design, battery, connectivity
- For clothing: material/fabric, fit and style, occasions, care instructions
- For furniture: build and material, dimensions, room placement, assembly
- For decor: design and aesthetics, craftsmanship, placement, occasions
- For industrial/safety: protection rating, durability, compliance, applications
- Adapt naturally — a perfume needs different headers than a laptop

CONTENT RULES:
- Every paragraph must be benefit-first: explain what the user gains from this spec
- Weave real-world examples naturally into every section (e.g. "students can run Zoom and documents together without slowdown")
- Do NOT write a separate use cases section — integrate examples throughout
- Mention variant/configuration options (memory, storage, color, size) naturally where relevant
- Last section must be a closing paragraph starting with "Buy [product name]" — mention availability and configurations

FACTUAL ACCURACY — STRICTLY ENFORCED:
- Use ONLY the facts explicitly listed in the product data above
- Do NOT infer, assume, or add ANY feature not directly stated in the specifications
- Do NOT embellish specs (e.g. 'cVc mic' must NOT become 'noise cancellation')
- Do NOT mention certifications, ratings, or compatibility not in the product data
- If it is not in the product data, do not write about it

FORMATTING:
- Separate every section with \\n\\n
- Bold section headers using **header text**
- Total length: 450-500 words — count carefully, do not go under 450

feature_bullets rules:
- Exactly 5 bullets
- Each bullet is a factual spec or key benefit, under 15 words
- No marketing fluff, no hashtags

Return ONLY the JSON object. Nothing else."""


def _build_social_system_prompt(tone: str, language: str, region: str, target_audience: Optional[str] = None) -> str:
    tone_guidance = {
        "formal":     "Write in a professional, brand-authoritative voice with controlled excitement — suitable for corporate Facebook pages.",
        "casual":     "Write in a friendly, hype-driven conversational voice with energy — suitable for Instagram and Facebook consumer audiences.",
        "persuasive": "Write in a high-energy, benefit-driven voice that creates urgency, excitement, and strong purchase intent.",
    }
    persona_block = ""
    instruction = _get_persona_instruction(target_audience)
    if instruction:
        persona_block = f"\n\nAUDIENCE TARGETING — STRICTLY FOLLOW:\n{instruction}"
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


def _build_variants_system_prompt(language: str, region: str) -> str:
    persona_block = ""
    instruction = _get_persona_instruction(target_audience)
    if instruction:
        persona_block = f"\n\nAUDIENCE TARGETING — STRICTLY FOLLOW:\n{instruction}"

    return (
        f"You are a world-class social media copywriter specialising in ecommerce product promotions "
        f"for Facebook and Instagram. "
        f"Write all output in {language.upper()} language, optimised for the {region} market. "
        f"You write in flowing conversational paragraphs — never bullet points, never section headers. "
        f"Every sentence must reference actual product data — zero hollow filler phrases. "
        f"You are capable of switching writing styles dramatically: from hype drops to quiet storytelling "
        f"to minimalist punch — each variant must feel distinctly different from the others. "
        f"Return ONLY valid JSON — no markdown, no code fences, no preamble."
    )


def _build_variants_user_prompt(
    product_summary: str,
    styles: list[dict],
    price: Union[str, float, None],
    shop_address: Optional[str],
) -> str:
    price_instruction = (
        f'Each variant MUST end with the line: "[Product Name] — Price: {price}/-"'
        if price else
        "Omit the price line if no price was provided."
    )

    address_instruction = (
        f'Each variant MUST end with: "Visit our outlet at {shop_address} or order online for the fastest delivery."'
        if shop_address else
        'End each variant with the equivalent of "Visit our outlet or order online for the fastest delivery."'
    )

    styles_block = "\n".join(
        f'{i+1}. Label: "{s["label"]}"\n   Style: {s["description"]}'
        for i, s in enumerate(styles)
    )

    n = len(styles)

    return f"""Generate {n} distinct social media post variants for this product.
Each variant must follow a completely different writing style as described below.

PRODUCT DATA:
{product_summary}

STYLES TO GENERATE (one variant per style):
{styles_block}

Return a single JSON object with exactly this key:
{{
  "variants": [
    {{
      "label": "<style label from above>",
      "post_body": "<full caption — follow ALL rules below>",
      "hashtags": ["tag1", "tag2", "tag3", "tag4", "tag5"]
    }},
    ... (one object per style, in the same order)
  ]
}}

RULES FOR EVERY variant:

STRUCTURE:
1. HOOK LINE: A single compelling opening line that matches the style. Wrap in markdown bold (**like this**).
   Separate from next paragraph with a blank line.

2. BODY (2–3 short paragraphs):
   - Flowing conversational sentences — NO bullet points, NO headers.
   - Every sentence references actual product specs.
   - Benefit-first writing: what the user GAINS.
   - 2–3 sentences per paragraph, separated by blank lines.
   - Adapt the voice and energy to match the style description.

3. CLOSING LINE(S) — MANDATORY, in this order:
   {price_instruction}
   {address_instruction}
   No bold on closing lines.

STRICT RULES:
- Each variant must feel DISTINCTLY different in voice, hook, and angle from all others.
- Do NOT repeat the same opening phrase or hook structure across variants.
- NO bullet points anywhere in post_body.
- NO hashtags inside post_body — they go in the hashtags list only.
- Separate every paragraph with \\n\\n.
- Total post_body per variant: 100–170 words.
- Use ONLY facts from the product data. Do NOT invent specs.

hashtags rules (per variant):
- 5 to 10 hashtags, single compound words (e.g. "JisulifeFan", "TurboFan").
- Include: brand, model, category, 1–2 generic tags, 1 regional tag.
- No # symbol — just the word.

Return ONLY the JSON object. Nothing else."""


def _build_ad_user_prompt(
    product_summary: str,
    price: Union[str, float, None],
    shop_address: str,
) -> str:
    price_line = f"{price}/-" if price is not None else "see below"

    return f"""Generate a Facebook and Instagram product ad caption for this product:

{product_summary}

MANDATORY FIELDS — these MUST appear verbatim in the output:
  Price: {price_line}
  Shop address: {shop_address}

Return a single JSON object with exactly these keys:
{{
  "post_body": "<the full caption — follow ALL rules below>",
  "hashtags": ["hashtag1", "hashtag2", "hashtag3", "hashtag4", "hashtag5"]
}}

post_body rules — follow this EXACT structure:

1. HOOK LINE (1 line):
   - Wrap the ENTIRE line in markdown bold (**like this**).
   - Pattern: "Want both [benefit 1] and [benefit 2] at the same time? Then the [Product Name] is now available at the best price at [Brand Name]."
   - [benefit 1] and [benefit 2] must come from actual product specs.
   - Separate from the next paragraph with a blank line (\\n\\n).

2. BODY PARAGRAPHS (2-3 short paragraphs):
   - Flowing conversational sentences — NO bullet points, NO section headers.
   - Every sentence references actual product specs from the data provided.
   - Benefit-first: what the user GAINS, not just the spec name.
   - 2-3 sentences per paragraph, separated by blank lines (\\n\\n).
   - No bold in body paragraphs.

3. PRICE LINE (MANDATORY — do NOT skip or reword):
   - Write this line exactly: "[Product Name] — Price: {price_line}"
   - This line is NON-NEGOTIABLE. It must appear word-for-word.
   - No bold on this line.
   - Separate from the next line with a blank line (\\n\\n).

4. CTA + ADDRESS LINE (MANDATORY — do NOT skip or reword):
   - Write this line exactly: "Visit our outlet at {shop_address} or order online for the fastest delivery."
   - This line is NON-NEGOTIABLE. It must appear word-for-word.
   - No bold on this line.

STRICT RULES:
- DO NOT omit the price line under any circumstance.
- DO NOT omit the shop address line under any circumstance.
- DO NOT paraphrase or summarise the price or address — copy them verbatim.
- DO NOT use bullet points anywhere in post_body.
- DO NOT include hashtags inside post_body.
- Separate every section with \\n\\n.
- Total post_body length: 120-170 words.

hashtags rules:
- Between 5 and 10 hashtags.
- Single compound words, no spaces (e.g. "EdifierX3S", "TWSEarbuds").
- Include: brand, model, category, 1-2 tech tags, 1 regional tag.
- No # symbol — just the word.

Return ONLY the JSON object. Nothing else."""


# ---------------------------------------------------------------------------
# Improve description prompt builders
# ---------------------------------------------------------------------------

def _build_improve_system_prompt(tone: str, language: str, region: str, length: str = "long") -> str:
    min_w, max_w = DESCRIPTION_LENGTH_PRESETS.get(length, (450, 500))
    tone_guidance = {
        "formal":     "Use professional, authoritative language suitable for premium or B2B product pages.",
        "casual":     "Use friendly, approachable language suitable for everyday consumer products.",
        "persuasive": "Use benefit-driven, value-focused language that builds confidence and encourages purchase.",
    }
    return (
        f"You are an expert ecommerce copywriter and editor. "
        f"Your job is to rewrite user-submitted product descriptions into polished, "
        f"compelling copy — preserving every fact, spec, and claim exactly as provided. "
        f"Write all output in {language.upper()} language, optimised for the {region} market. "
        f"Tone: {tone_guidance.get(tone, 'professional and benefit-driven')} "
        f"STRICT RULE: Do NOT invent, add, or remove any product fact, specification, price, "
        f"dimension, or claim. Only improve the writing quality, structure, and tone. "
        f"Target output length is {min_w}–{max_w} words. "
        f"If your draft is under {min_w} words, expand each paragraph before returning. "
        f"If your draft exceeds {max_w} words, trim without removing any facts. "
        f"Return ONLY valid JSON — no markdown, no code fences, no preamble."
    )


def _build_improve_user_prompt(raw_description: str, length: str = "long") -> str:
    min_w, max_w = DESCRIPTION_LENGTH_PRESETS.get(length, (450, 500))

    # Section structure guidance scales with the target length so the model
    # doesn't try to fit 6 sections into a 150-word output.
    if length == "short":
        structure_note = (
            "Use 1–2 sections with brief, focused headers. "
            "Each section is a single tight paragraph. "
            "Keep every sentence essential — no filler."
        )
    elif length == "medium":
        structure_note = (
            "Use 2–3 sections with clear headers. "
            "Each section has 1 paragraph of 3–4 sentences. "
            "Cover the key specs and one benefit per section."
        )
    else:  # long
        structure_note = (
            "Use 4–6 sections with dynamic headers suited to the product type. "
            "Each section has 1–2 paragraphs of benefit-first storytelling content. "
            "Last section must be a closing 'Buy' paragraph mentioning availability and price."
        )

    return f"""Rewrite the following product description with improved writing quality and tone.

RAW DESCRIPTION:
{raw_description}

Return a single JSON object with exactly this key:
{{
  "improved_description": "<rewritten description — follow ALL rules below>"
}}

Rules:
1. PRESERVE FACTS: Every spec, price, dimension, model number, and claim must remain unchanged.
2. IMPROVE QUALITY: Fix grammar, flow, sentence structure, and word choice.
3. APPLY TONE: Rewrite to match the tone defined in your instructions.
4. LENGTH: Output must be {min_w}–{max_w} words. Count carefully. Do not go under {min_w} words.
5. LANGUAGE: Write in the same language as the input. If Bengali and English are mixed, respond in English.
6. NO ADDITIONS: Do not add features, benefits, or claims not present in the original.
7. FORMAT: Use structured section headers exactly like this:

   - Line 1: Full product name as a standalone title (no label, just the name)
   - {structure_note}
   - Bold every section header (e.g. **48MP Fusion Camera System**)
   - Blank line after each header
   - Blank line between sections
   - No bullet points anywhere
   - Separate every section with \\n\\n

Return ONLY the JSON object. Nothing else."""

# ---------------------------------------------------------------------------
# Audience persona definitions
# ---------------------------------------------------------------------------

AUDIENCE_PERSONA_INSTRUCTIONS: dict[str, str] = {
    "students": (
        "Target audience: university and high school students. "
        "Emphasise: affordability and value for money, portability for carrying between classes, "
        "performance for studying, assignments, and light multitasking (Zoom, docs, browsing). "
        "Tone: relatable, peer-to-peer, budget-conscious. "
        "Avoid: corporate language, luxury positioning, enterprise features."
    ),
    "gamers": (
        "Target audience: PC and mobile gamers aged 16–30. "
        "Emphasise: processing power, GPU/display specs, frame rates, cooling, low-latency peripherals. "
        "Use gaming vocabulary naturally (fps, lag, smooth gameplay, sessions). "
        "Tone: hyped, technical, community-driven. "
        "Avoid: office/productivity framing, boring professional language."
    ),
    "professionals": (
        "Target audience: working professionals — engineers, managers, consultants. "
        "Emphasise: productivity, reliability, build quality, compatibility with professional tools. "
        "Tone: polished, confident, ROI-aware. "
        "Avoid: casual slang, gamer language, budget-focused framing."
    ),
    "parents": (
        "Target audience: parents shopping for family use or for their children. "
        "Emphasise: durability, safety, ease of use, parental controls where relevant, value for family. "
        "Tone: warm, reassuring, practical. "
        "Avoid: overly technical jargon, hype language, gaming/nightlife associations."
    ),
    "business_owners": (
        "Target audience: small to medium business owners and entrepreneurs. "
        "Emphasise: ROI, operational efficiency, reliability, scalability, time-saving. "
        "Tone: direct, results-oriented, professional. "
        "Avoid: consumer-lifestyle framing, entertainment features, budget positioning."
    ),
    "content_creators": (
        "Target audience: YouTubers, streamers, photographers, video editors, social media influencers. "
        "Emphasise: camera quality, display colour accuracy, processing speed for editing, "
        "storage for large files, portability for on-location shoots. "
        "Tone: creative, aspirational, tool-focused. "
        "Avoid: boring office framing, purely technical spec-listing."
    ),
    "travelers": (
        "Target audience: frequent travellers, digital nomads, backpackers. "
        "Emphasise: lightweight design, battery life, durability, compact form factor, "
        "compatibility with travel accessories, offline capability. "
        "Tone: adventurous, freedom-oriented, practical. "
        "Avoid: desk-setup framing, heavy enterprise features, stationary use cases."
    ),
}


def _get_persona_instruction(target_audience: Optional[str]) -> str:
    """Return the persona instruction string, or empty string if no persona set."""
    if not target_audience:
        return ""
    key = target_audience.lower().strip().replace(" ", "_")
    instruction = AUDIENCE_PERSONA_INSTRUCTIONS.get(key)
    if not instruction:
        # Unknown persona — pass it through generically rather than silently dropping it
        return (
            f"Target audience: {target_audience}. "
            f"Tailor all language, benefit framing, and examples specifically to this audience."
        )
    return instruction


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
        price: Union[str, float, None],
        region: str,
        language: str,
        tone: str,
        query: Optional[str] = None,
    ) -> dict:
        """Generate ecommerce product description page content via OpenAI."""
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
        price: Union[str, float, None],
        region: str,
        language: str,
        tone: str,
        query: Optional[str] = None,
        shop_address: Optional[str] = None,
        target_audience: Optional[str] = None,
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

    @staticmethod
    def generate_social_variants(
        name: str,
        category: Optional[str],
        brand: Optional[str],
        specifications: list[str],
        price: Union[str, float, None],
        region: str,
        language: str,
        shop_address: Optional[str] = None,
        count: int = 4,
        target_audience: Optional[str] = None,
    ) -> list[dict]:
        count  = max(1, min(count, len(VARIANT_STYLES)))
        styles = VARIANT_STYLES[:count]

        product_summary = _build_product_summary(name, category, brand, specifications, price)
        system_prompt   = _build_variants_system_prompt(language, region)
        user_prompt     = _build_variants_user_prompt(product_summary, styles, price, shop_address)

        raw = ContentGenerationService._call_openai(
            system_prompt, user_prompt, name, "VariantsGen",
            max_tokens_override=4096,
        )

        result = ContentGenerationService._parse_and_validate(raw, {"variants"})

        if not isinstance(result.get("variants"), list):
            raise LLMGenerationError("variants must be a list")

        cleaned = []
        for v in result["variants"]:
            if not isinstance(v, dict):
                continue
            post_body = str(v.get("post_body", "")).strip()
            hashtags  = [str(h).strip().lstrip("#") for h in v.get("hashtags", []) if h]
            label     = str(v.get("label", "")).strip()

            if post_body:
                # Strip any LLM-generated CTA so we can inject deterministically.
                lines     = post_body.rstrip().split("\n")
                last_line = lines[-1].strip().lower()
                cta_triggers = ("visit our outlet", "order online", "fastest delivery")
                if any(t in last_line for t in cta_triggers):
                    post_body = "\n".join(lines[:-1]).rstrip()

                if price:
                    # Remove any existing price line before re-injecting.
                    price_trigger = str(price).lower()
                    filtered = [
                        ln for ln in post_body.split("\n")
                        if not ("price:" in ln.lower() and price_trigger in ln.lower())
                    ]
                    post_body  = "\n".join(filtered).rstrip()
                    price_line = f"{name} — Price: {price}/-"
                    cta_line   = (
                        f"Visit our outlet at {shop_address} or order online for the fastest delivery."
                        if shop_address else
                        "Visit our outlet or order online for the fastest delivery."
                    )
                    post_body = f"{post_body}\n\n{price_line}\n{cta_line}"
                elif shop_address:
                    cta_line  = f"Visit our outlet at {shop_address} or order online for the fastest delivery."
                    post_body = f"{post_body}\n\n{cta_line}"

            cleaned.append({
                "label":     label,
                "post_body": post_body,
                "hashtags":  hashtags,
            })

        if not cleaned:
            raise LLMGenerationError("No valid variants returned by OpenAI")

        return cleaned

    @staticmethod
    def generate_ad(
        name: str,
        category: Optional[str],
        brand: Optional[str],
        specifications: list[str],
        price: Union[str, float, None],
        shop_address: str,
        region: str,
        language: str,
        tone: str,
        target_audience: Optional[str] = None,
    ) -> dict:
        """Generate a social media ad post with price and shop address via OpenAI."""
        product_summary = _build_product_summary(name, category, brand, specifications, price)
        system_prompt   = _build_social_system_prompt(tone, language, region)
        user_prompt     = _build_ad_user_prompt(product_summary, price, shop_address)

        raw = ContentGenerationService._call_openai(system_prompt, user_prompt, name, "AdGen")

        result = ContentGenerationService._parse_and_validate(raw, {"post_body", "hashtags"})

        if not isinstance(result.get("hashtags"), list):
            raise LLMGenerationError("hashtags must be a list")

        post_body = str(result["post_body"]).strip()

        price_str = str(price) if price is not None else ""
        if price_str and price_str not in post_body:
            logger.warning(
                "[AdGen] Price '%s' missing from generated post_body for '%s'",
                price_str, name,
            )
        if shop_address and shop_address not in post_body:
            logger.warning(
                "[AdGen] shop_address '%s' missing from generated post_body for '%s'",
                shop_address, name,
            )

        return {
            "post_body": post_body,
            "hashtags":  [str(h).strip().lstrip("#") for h in result["hashtags"] if h],
        }

    @staticmethod
    def improve_description(
        raw_description: str,
        tone: str,
        language: str,
        region: str,
        length: str = "long",
    ) -> dict:
        """
        Improve a user-written product description via OpenAI.

        length preset controls output word count:
          - short:  150–200 words  (1–2 sections)
          - medium: 300–350 words  (2–3 sections)
          - long:   450–500 words  (4–6 sections, default)
        """
        system_prompt = _build_improve_system_prompt(tone, language, region, length)
        user_prompt   = _build_improve_user_prompt(raw_description, length)

        raw = ContentGenerationService._call_openai(
            system_prompt, user_prompt, "user_description", "ImproveDesc",
        )
        return ContentGenerationService._parse_and_validate(raw, {"improved_description"})

    # ── Shared OpenAI call ─────────────────────────────────────────────────

    @staticmethod
    def _call_openai(
        system_prompt: str,
        user_prompt: str,
        name: str,
        log_tag: str,
        max_tokens_override: Optional[int] = None,
    ) -> str:
        # DESCRIPTION_MAX_TOKENS is intentionally capped below the model's
        # output limit (~500 words ≈ 700 tokens; 2048 gives comfortable headroom
        # for long presets without ballooning cost on every request).
        max_tokens = max_tokens_override or DESCRIPTION_MAX_TOKENS

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
        except OpenAIRateLimitError as e:
            logger.warning("[%s] Rate limit hit: %s", log_tag, e)
            raise RateLimitError(f"OpenAI rate limit exceeded: {e}")
        except AuthenticationError as e:
            raise LLMGenerationError(f"OpenAI authentication error: {e}")
        except APIConnectionError as e:
            raise LLMGenerationError(f"OpenAI network error: {e}")
        except Exception as e:
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