

from __future__ import annotations

import logging
import re
import time
from enum import Enum
from typing import Dict, Tuple

from openai import AsyncOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

OFF_TOPIC_RESPONSE = "I can only help with product search."

_MAX_QUERY_LEN     = 350
_LLM_TIMEOUT       = 5.0
_LLM_MAX_TOKENS    = 5
_CACHE_MAX_SIZE    = 1024
_CACHE_TTL_SECONDS = 3600

# ─── Stdlib TTL cache ─────────────────────────────────────────────────────────

class _TTLCache:
    def __init__(self, maxsize: int, ttl: float) -> None:
        self._maxsize = maxsize
        self._ttl     = ttl
        self._store:  Dict[str, Tuple[bool, float]] = {}

    def get(self, key: str) -> bool | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: bool) -> None:
        if len(self._store) >= self._maxsize and key not in self._store:
            oldest_key = next(iter(self._store))
            del self._store[oldest_key]
        self._store[key] = (value, time.monotonic() + self._ttl)

    def __len__(self) -> int:
        return len(self._store)


# ─── Brand / product keyword config ───────────────────────────────────────────

_KNOWN_BRANDS: frozenset[str] = frozenset({
    "nike", "adidas", "puma", "reebok",
    "samsung", "apple", "sony", "lg", "hp", "dell",
    "asus", "lenovo", "xiaomi", "realme", "oneplus",
    "google", "microsoft", "huawei", "oppo", "vivo",
    "anker", "jbl", "bose", "sennheiser", "skullcandy",
    "gopro", "canon", "nikon", "fujifilm",
})

_PRODUCT_KEYWORDS: frozenset[str] = frozenset({
    # Commerce intent
    "buy", "price", "cost", "taka", "tk", "under", "below",
    "above", "budget", "cheap", "sosta", "brand", "model",
    "spec", "feature", "review", "rating", "stock", "available",
    "ache", "pabo", "recommend", "suggest", "best", "top",
    "vs", "compare",

    # Product categories
    "wireless", "bluetooth", "camera", "laptop", "phone", "mobile",
    "headphone", "earphone", "watch", "tablet", "tv", "monitor",
    "keyboard", "mouse", "charger", "cable", "bag", "shoe",
    "shirt", "pant", "dress", "jacket",

    # Bengali / Banglish actions
    "dekhao", "lagbe", "kinbo", "nibo", "dao",

    # Occupations
    "engineer", "developer", "programmer", "designer", "photographer",
    "videographer", "doctor", "nurse", "teacher", "chef", "cook",
    "athlete", "runner", "cyclist", "gamer", "student", "freelancer",
    "architect", "artist", "musician", "carpenter", "tailor", "writer",
    "journalist", "lawyer", "accountant", "trader", "businessman",

    # Bengali occupations
    "ইঞ্জিনিয়ার", "ডেভেলপার", "ডাক্তার", "শিক্ষক", "ফটোগ্রাফার",
    "গেমার", "ছাত্র", "শিক্ষার্থী", "উদ্যোক্তা", "ব্যবসায়ী",
    "নার্স", "শিল্পী", "সংগীতশিল্পী",

    # Tech stack words
    "docker", "redis", "postgresql", "postgres", "mongodb", "mysql",
    "linux", "ubuntu", "python", "javascript", "react", "nodejs",
    "kubernetes",

    # Activity / routine words
    "travel", "commute", "carry", "portable", "outdoor", "indoor",
    "ভ্রমণ", "যাতায়াত", "অফিস", "office",
})

# ─── Verdict enum ─────────────────────────────────────────────────────────────

class _GateVerdict(Enum):
    ALLOW  = "allow"
    BLOCK  = "block"
    UNSURE = "unsure"

# ─── Layer 1: Rule-based patterns ────────────────────────────────────────────

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

_GIBBERISH_RE = re.compile(
    r"^[^a-zA-Z\u0980-\u09FF\d]+$"
    r"|^(.)\1{4,}$",
    re.IGNORECASE,
)

# ── NEW: use-case / implicit product request pattern ─────────────────────────
# Detects queries where the user describes their lifestyle, job, or daily
# routine instead of naming a product directly.
# Pattern-based, not domain-specific — works for ANY product category.
_USECASE_RE = re.compile(
    r"("
    # First-person statements in any language
    r"আমি|ami\b|আমার|amar\b|"
    r"I\s+am\b|I\s+work|I\s+do\b|I\s+use\b|I\s+need\b|"
    r"I\s+travel|I\s+commute|I\s+carry|I\s+run|I\s+play|I\s+cook|"
    r"I\s+shoot|I\s+edit|I\s+design|I\s+code|I\s+teach|I\s+ride|"

    # Routine / frequency signals
    r"সারাদিন|প্রতিদিন|প্রতিরাত|সবসময়|"
    r"all\s*day|every\s*day|daily|always|regularly|constantly|"
    r"all\s*night|every\s*night|"

    # Physical context / environment
    r"outdoor|indoor|on\s*the\s*go|in\s*the\s*field|"
    r"বাইরে|মাঠে|রান্নাঘরে|স্টুডিওতে|"

    # Job / work context
    r"remote\s*job|work\s*from\s*home|office\s*work|field\s*work|"
    r"রিমোট\s*জব|ঘরে\s*বসে\s*কাজ|অফিসে\s*কাজ|"

    # Pain / discomfort signals
    r"back\s*pain|wrist\s*pain|eye\s*strain|neck\s*pain|shoulder\s*pain|"
    r"পিঠে\s*ব্যথা|কব্জিতে\s*ব্যথা|চোখে\s*সমস্যা|ঘাড়ে\s*ব্যথা|"

    # Distance / duration with units
    r"\d+\s*(km|কিলোমিটার|miles?|hours?|ঘণ্টা|minutes?|মিনিট|"
    r"kg|কেজি|liters?|লিটার)\b|"

    # Tech stack
    r"docker|redis|postgresql|postgres|mongodb|mysql|linux|ubuntu|"
    r"python|javascript|typescript|react|nodejs|kubernetes|ansible|"

    # Professional activity verbs
    r"photograph|videograph|record\s*video|live\s*stream|stream\s*games|"
    r"ছবি\s*তুলি|ভিডিও\s*করি|লাইভ\s*করি|"
    r"play\s*guitar|play\s*piano|play\s*drums|practice\s*music|"
    r"গিটার\s*বাজাই|গান\s*করি|"
    r"cook\s*professionally|run\s*marathon|cycle\s*daily|"
    r"রান্না\s*করি|সেলাই\s*করি|বুনন\s*করি"
    r")",
    re.IGNORECASE,
)


def _build_product_signal_pattern() -> re.Pattern[str]:
    all_terms = _PRODUCT_KEYWORDS | _KNOWN_BRANDS
    escaped   = sorted(re.escape(t) for t in all_terms)
    pattern   = r"\b(" + "|".join(escaped) + r")\b"
    return re.compile(pattern, re.IGNORECASE)


_PRODUCT_SIGNAL_RE = _build_product_signal_pattern()


def _rule_based_check(query: str) -> _GateVerdict:
    """
    Fast rule-based pre-filter.

    Returns:
        BLOCK  — greeting, chitchat, or gibberish
        ALLOW  — known product keyword/brand OR use-case description
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

    # NEW: implicit use-case / lifestyle description
    if _USECASE_RE.search(q):
        logger.debug("Intent gate [rule] ALLOW use-case signal | query=%r", q)
        return _GateVerdict.ALLOW

    return _GateVerdict.UNSURE


# ─── Layer 2: LLM-based gate ─────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a strict query relevance classifier for an AI-powered e-commerce product search engine.

Your ONLY job is to decide if a user query is relevant to product search.

A query IS relevant if it involves:
- Searching, finding, or browsing products
- Asking about product features, specs, price, or availability
- Comparing products or brands
- Requesting recommendations or suggestions for products
- Any product category: electronics, clothing, accessories, gadgets, appliances,
  kitchen tools, sports equipment, musical instruments, medical devices, etc.
- Banglish or Bengali queries about products (e.g. "valo headphone dao", "samsung phone ache?")

IMPORTANT — IMPLICIT PRODUCT REQUESTS:
A query is ALSO relevant if the user describes their lifestyle, job, use case,
or daily routine in a way that clearly implies they want a product recommendation.
These are NOT off-topic even though they contain no explicit product name or question.

Examples of IMPLICIT but RELEVANT queries — always return true for these:
- "আমি Software Engineer। Remote job করি। সারাদিন Docker, Redis আর PostgreSQL চালাই।
   আমি প্রতিদিন অফিসে ল্যাপটপ নিয়ে যাই। অনেক ভ্রমণ করি।"
  -> User wants a laptop recommendation. true.

- "I travel a lot and need something lightweight with good battery life."
  -> User wants a laptop or bag recommendation. true.

- "আমি প্রতিদিন অফিসে যাই, অনেক হাঁটতে হয়।"
  -> User wants comfortable shoes or a bag. true.

- "I work from home and my back hurts from sitting all day."
  -> User wants an ergonomic chair or desk. true.

- "আমি গেমার, রাত জেগে গেম খেলি।"
  -> User wants gaming gear. true.

- "I am a photographer and shoot outdoors in all weather."
  -> User wants a camera bag or weather-sealed camera. true.

- "আমি রান্না করি, সারাদিন রান্নাঘরে থাকি।"
  -> User wants kitchen appliances or tools. true.

- "I cycle 30km every day to work."
  -> User wants cycling gear, helmet, or bag. true.

- "আমি গিটার বাজাই, প্রতিদিন ৪ ঘণ্টা প্র্যাকটিস করি।"
  -> User wants guitar accessories or amplifier. true.

- "I am a nurse and stand for 12 hours a day."
  -> User wants comfortable shoes or compression socks. true.

- "আমি সেলাই করি। অনেকক্ষণ বসে কাজ করতে হয়।"
  -> User wants a sewing machine or ergonomic chair. true.

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

_llm_gate_client: AsyncOpenAI = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
_gate_cache = _TTLCache(maxsize=_CACHE_MAX_SIZE, ttl=_CACHE_TTL_SECONDS)


def _sanitize_query(query: str) -> str:
    sanitized = query.replace('"', "'").replace("\n", " ").replace("\r", " ")
    return sanitized[:_MAX_QUERY_LEN].strip()


async def _llm_based_check(query: str) -> bool:
    """
    LLM-based relevance gate using gpt-4o-mini.
    Returns True if relevant, False if off-topic.
    Falls back to True (allow) on any error.
    Results cached for 1 hour per unique query.
    """
    cache_key = query.strip().lower()

    cached = _gate_cache.get(cache_key)
    if cached is not None:
        logger.debug(
            "Intent gate [LLM cache HIT] | query=%r | result=%s",
            query, cached,
        )
        return cached

    sanitized   = _sanitize_query(query)
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

        _gate_cache.set(cache_key, result)

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
        return True  # fail open


# ─── Public API ───────────────────────────────────────────────────────────────

async def is_relevant_query(query: str) -> bool:
    """
    Two-layer relevance gate.

    Layer 1 — Rule-based (zero cost, <1ms):
      BLOCK:  gibberish, greetings, chitchat
      ALLOW:  known product keyword/brand OR use-case/lifestyle description
      UNSURE: escalate to LLM

    Layer 2 — LLM gate (only for UNSURE):
      gpt-4o-mini with implicit request examples in system prompt
      Cached 1 hour per unique query
      Fails open on error

    Returns:
        True  — proceed to classifier + search
        False — return off-topic response to caller
    """
    if not query or not query.strip():
        return False

    verdict = _rule_based_check(query)

    if verdict == _GateVerdict.ALLOW:
        return True
    if verdict == _GateVerdict.BLOCK:
        return False

    return await _llm_based_check(query)