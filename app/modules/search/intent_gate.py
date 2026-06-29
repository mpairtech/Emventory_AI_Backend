"""
Intent Gate — relevance pre-check before the main classifier.

Two-layer design:
  Layer 1: Rule-based (zero cost, <1ms)  — kills obvious off-topic queries
  Layer 2: LLM-based  (gpt-4o-mini)     — handles ambiguous cases

Only queries that pass BOTH layers proceed to classify_and_extract()
and the full search pipeline.

Fixes applied (v2):
  - Singleton client initialized at module level (thread-safe)
  - _GateVerdict enum replaces bool | None return type
  - _GIBBERISH_RE logic error fixed (no longer blocks "TV", "I", "AI")
  - Prompt injection sanitization on user query
  - TTL cache on LLM gate results (avoids redundant API calls)
  - Brand list moved to a frozenset config (maintainable)
  - Constants grouped at top of file
  - Query length cap before LLM call
"""

from __future__ import annotations

import logging
import re
from enum import Enum

from cachetools import TTLCache
from openai import AsyncOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

OFF_TOPIC_RESPONSE = "I can only help with product search."

_MAX_QUERY_LEN     = 300    # chars — anything longer gets truncated before LLM
_LLM_TIMEOUT       = 5.0    # seconds
_LLM_MAX_TOKENS    = 5      # only "true" or "false" needed
_CACHE_MAX_SIZE    = 1024   # max unique queries cached
_CACHE_TTL_SECONDS = 3600   # 1 hour — gate result unlikely to change per query

# ─── Brand / product keyword config (extend here, not in regex) ───────────────

_KNOWN_BRANDS: frozenset[str] = frozenset({
    "nike", "adidas", "puma", "reebok",
    "samsung", "apple", "sony", "lg", "hp", "dell",
    "asus", "lenovo", "xiaomi", "realme", "oneplus",
    "google", "microsoft", "huawei", "oppo", "vivo",
    "anker", "jbl", "bose", "sennheiser", "skullcandy",
    "gopro", "canon", "nikon", "fujifilm",
})

_PRODUCT_KEYWORDS: frozenset[str] = frozenset({
    "buy", "price", "cost", "taka", "tk", "under", "below",
    "above", "budget", "cheap", "sosta", "brand", "model",
    "spec", "feature", "review", "rating", "stock", "available",
    "ache", "pabo", "recommend", "suggest", "best", "top",
    "vs", "compare", "wireless", "bluetooth", "camera", "laptop",
    "phone", "mobile", "headphone", "earphone", "watch", "tablet",
    "tv", "monitor", "keyboard", "mouse", "charger", "cable",
    "bag", "shoe", "shirt", "pant", "dress", "jacket", "dekhao",
})

# ─── Verdict enum (replaces bool | None) ──────────────────────────────────────

class _GateVerdict(Enum):
    ALLOW  = "allow"   # definitely product-related, skip LLM
    BLOCK  = "block"   # definitely off-topic, skip LLM
    UNSURE = "unsure"  # ambiguous, escalate to LLM gate

# ─── Layer 1: Rule-based patterns (zero LLM cost) ────────────────────────────

_GREET_RE = re.compile(
    r"^(hi+|hello+|hey+|howdy|greetings|salaam|assalamu\s*alaikum|"
    r"good\s*(morning|afternoon|evening|night|day)|"
    r"kemon\s*acho|ki\s*obostha|kire|vai\s*ki\s*koro|"
    r"how\s*are\s*you|what'?s\s*up|sup|yo+)\b.*$",
    re.IGNORECASE,
)

_CHITCHAT_RE = re.compile(
    r"^(thanks?|thank\s*you|dhonnobad|shukriya|ok(ay)?|sure|"
    r"nice|cool|great|lol|haha|wow|bye|goodbye|see\s*ya|"
    r"who\s*are\s*you|what\s*are\s*you|apni\s*ke|tumi\s*ki|"
    r"tell\s*me\s*a\s*joke|sing\s*a\s*song|write\s*a\s*poem|"
    r"what\s*is\s*(ai|ml|chatgpt|gpt)|explain\s*(ai|ml|blockchain|crypto))\b.*$",
    re.IGNORECASE,
)

# Fixed: no longer blocks "TV", "I", "A1", "LG" etc.
# Only blocks: purely non-letter strings, or single repeated char 5+ times
_GIBBERISH_RE = re.compile(
    r"^[^a-zA-Z\u0980-\u09FF\d]+$"   # no letters or digits at all (e.g. "!!!###")
    r"|^(.)\1{4,}$",                  # single char repeated 5+ times (e.g. "aaaaa")
    re.IGNORECASE,
)


def _build_product_signal_pattern() -> re.Pattern[str]:
    """Build product signal regex from config sets — single source of truth."""
    all_terms = _PRODUCT_KEYWORDS | _KNOWN_BRANDS
    escaped   = sorted(re.escape(t) for t in all_terms)
    pattern   = r"\b(" + "|".join(escaped) + r")\b"
    return re.compile(pattern, re.IGNORECASE)


_PRODUCT_SIGNAL_RE = _build_product_signal_pattern()


def _rule_based_check(query: str) -> _GateVerdict:
    """
    Fast rule-based pre-filter. Zero LLM cost.

    Returns:
        BLOCK  — definitely off-topic (greeting, chitchat, gibberish)
        ALLOW  — definitely product-related (known brand/keyword signal)
        UNSURE — ambiguous, escalate to LLM gate
    """
    q = query.strip()

    if not q or len(q) < 2:
        logger.debug("Intent gate [rule] BLOCK empty/too-short | query=%r", q)
        return _GateVerdict.BLOCK

    if _GIBBERISH_RE.match(q):
        logger.debug("Intent gate [rule] BLOCK gibberish | query=%r", q)
        return _GateVerdict.BLOCK

    if _GREET_RE.match(q) or _CHITCHAT_RE.match(q):
        logger.debug("Intent gate [rule] BLOCK greeting/chitchat | query=%r", q)
        return _GateVerdict.BLOCK

    if _PRODUCT_SIGNAL_RE.search(q):
        logger.debug("Intent gate [rule] ALLOW product signal | query=%r", q)
        return _GateVerdict.ALLOW

    return _GateVerdict.UNSURE


# ─── Layer 2: LLM-based gate (gpt-4o-mini) ───────────────────────────────────

_SYSTEM_PROMPT = """\
You are a strict query relevance classifier for an AI-powered e-commerce product search engine.

Your ONLY job is to decide if a user query is relevant to product search.

A query IS relevant if it involves:
- Searching, finding, or browsing products
- Asking about product features, specs, price, or availability
- Comparing products or brands
- Requesting recommendations or suggestions for products
- Any product category: electronics, clothing, accessories, gadgets, appliances, etc.
- Banglish or Bengali queries about products (e.g. "valo headphone dao", "samsung phone ache?")

A query is NOT relevant if it involves:
- Greetings or chitchat ("hi", "kemon acho", "how are you")
- General knowledge questions unrelated to products ("what is AI", "explain blockchain")
- Personal questions about the assistant ("who are you", "apni ki")
- Creative requests ("write a poem", "tell a joke")
- Anything where no product could possibly be the answer

Respond with ONLY one word: true or false
- true  = query is relevant to product search
- false = query is irrelevant, off-topic, or chitchat

No explanation. No punctuation. Just: true or false"""

# Initialized once at module level — thread-safe, no lazy singleton needed
_llm_gate_client: AsyncOpenAI = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

# TTL cache: same query won't hit the LLM twice within 1 hour
_gate_cache: TTLCache[str, bool] = TTLCache(
    maxsize=_CACHE_MAX_SIZE,
    ttl=_CACHE_TTL_SECONDS,
)


def _sanitize_query(query: str) -> str:
    """
    Sanitize user input before embedding in LLM prompt.
    Prevents basic prompt injection via quote escaping and length cap.
    """
    sanitized = query.replace('"', "'").replace("\n", " ").replace("\r", " ")
    return sanitized[:_MAX_QUERY_LEN].strip()


async def _llm_based_check(query: str) -> bool:
    """
    LLM-based relevance gate using gpt-4o-mini with a strict system prompt.

    Returns True if relevant, False if off-topic.
    Falls back to True (allow) on any error — never block legitimate queries
    due to an infrastructure failure.

    Results are cached by normalized query for 1 hour to avoid redundant calls.
    """
    cache_key = query.strip().lower()

    # Check cache first
    cached = _gate_cache.get(cache_key)
    if cached is not None:
        logger.debug("Intent gate [LLM cache HIT] | query=%r | result=%s", query, cached)
        return cached

    sanitized = _sanitize_query(query)
    user_prompt = f'User query: "{sanitized}"'

    try:
        response = await _llm_gate_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0,
            max_tokens=_LLM_MAX_TOKENS,
            timeout=_LLM_TIMEOUT,
        )
        raw    = response.choices[0].message.content.strip().lower()
        result = raw.startswith("true")

        # Store in cache
        _gate_cache[cache_key] = result

        logger.info(
            "Intent gate [LLM] | query=%r | result=%s | raw=%r",
            query, result, raw,
        )
        return result

    except Exception:
        logger.warning(
            "Intent gate LLM failed for query=%r — defaulting to ALLOW",
            query,
            exc_info=True,
        )
        return True  # fail open: don't block legitimate queries on LLM error


# ─── Public API ───────────────────────────────────────────────────────────────

async def is_relevant_query(query: str) -> bool:
    """
    Two-layer relevance gate. Called before classify_and_extract().

    Layer 1 — Rule-based (zero cost, <1ms):
      - Gibberish / empty          → BLOCK immediately
      - Greetings / chitchat       → BLOCK immediately
      - Known product keyword/brand → ALLOW immediately

    Layer 2 — LLM gate (only for UNSURE queries):
      - gpt-4o-mini with strict system prompt
      - Results cached for 1 hour per unique query
      - Fails open on error (never blocks legitimate users)

    Returns:
        True  — query is product-relevant, proceed to classifier + search
        False — query is off-topic, return OFF_TOPIC_RESPONSE to caller
    """
    if not query or not query.strip():
        return False

    verdict = _rule_based_check(query)

    if verdict == _GateVerdict.ALLOW:
        return True
    if verdict == _GateVerdict.BLOCK:
        return False

    # UNSURE — escalate to LLM
    return await _llm_based_check(query)