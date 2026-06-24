from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, NamedTuple, Optional

from openai import AsyncOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)


class QueryType(str, Enum):
    KEYWORD  = "keyword"
    SEMANTIC = "semantic"
    BALANCED = "balanced"


class Intent(str, Enum):
    EXACT_LOOKUP   = "exact_lookup"
    RECOMMENDATION = "recommendation"
    COMPARISON     = "comparison"
    PRICE_FILTER   = "price_filter"
    AVAILABILITY   = "availability"
    FEATURE_SEARCH = "feature_search"
    BROWSE         = "browse"
    GENERAL        = "general"
    OFF_TOPIC      = "off_topic"


class _Weights(NamedTuple):
    vector: float
    bm25: float
    query_type: QueryType


WEIGHTS_KEYWORD  = _Weights(vector=0.2, bm25=0.8, query_type=QueryType.KEYWORD)
WEIGHTS_SEMANTIC = _Weights(vector=0.8, bm25=0.2, query_type=QueryType.SEMANTIC)
WEIGHTS_BALANCED = _Weights(vector=0.5, bm25=0.5, query_type=QueryType.BALANCED)
WEIGHTS_EXACT    = _Weights(vector=0.1, bm25=0.9, query_type=QueryType.KEYWORD)


@dataclass(frozen=True)
class QueryClassification:
    vector_weight:     float
    bm25_weight:       float
    query_type:        QueryType
    intent:            Intent
    intent_confidence: float


@dataclass(frozen=True)
class ClassificationResult:
    vector_weight:      float
    bm25_weight:        float
    query_type:         QueryType
    intent:             Intent
    intent_confidence:  float

    secondary_intents:  list[Intent] = field(default_factory=list)

    bm25_query:         str = ""

    price_max:          Optional[float] = None
    price_min:          Optional[float] = None
    brand:              Optional[str]   = None
    status:             Optional[str]   = None

    is_banglish:        bool = False
    is_size_query:      bool = False
    is_brand_query:     bool = False

    def to_query_classification(self) -> QueryClassification:
        return QueryClassification(
            vector_weight=self.vector_weight,
            bm25_weight=self.bm25_weight,
            query_type=self.query_type,
            intent=self.intent,
            intent_confidence=self.intent_confidence,
        )


_CLASSIFY_PROMPT = """\
You are a search query analyzer for an AI-powered e-commerce product search engine.

Analyze the user's search query and return a JSON object with classification and filter extraction combined.

User query: "{query}"

Return ONLY a JSON object with these fields:

{{
  "primary_intent": "<one of: exact_lookup, recommendation, comparison, price_filter, availability, feature_search, browse, general,off_topic>",
  "secondary_intents": ["<additional intents that also apply, can be empty list>"],
  "vector_weight": <float 0.0-1.0>,
  "bm25_weight": <float 0.0-1.0, must sum to 1.0 with vector_weight>,
  "query_type": "<keyword | semantic | balanced>",
  "intent_confidence": <float 0.0-1.0>,
  "bm25_query": "<cleaned query for BM25 lexical search>",
  "price_max": <number or null>,
  "price_min": <number or null>,
  "brand": "<brand name or null>",
  "status": "<ACTIVE | DISCONTINUED | DRAFT or null>",
  "is_banglish": <true | false>,
  "is_size_query": <true | false>,
  "is_brand_query": <true | false>
}}

WEIGHT RULES:
- Exact model/code lookup (e.g. "WF-1000XM5", "RTX 4060"): vector=0.1, bm25=0.9, type=keyword
- Brand + category noise (e.g. "gopro brand mobile", "sony er phone"): vector=0.5, bm25=0.5, type=balanced
- Recommendation/vague (e.g. "best headphones", "suggest a laptop"): vector=0.8, bm25=0.2, type=semantic
- Browse (e.g. "show all laptops", "list cameras"): vector=0.8, bm25=0.2, type=semantic
- Feature search (e.g. "wireless noise cancelling earbuds"): vector=0.6, bm25=0.4, type=balanced
- Price filter with brand (e.g. "Sony headphones under 5000"): vector=0.5, bm25=0.5, type=balanced
- Price filter no brand (e.g. "headphones under 5000"): vector=0.6, bm25=0.4, type=balanced
- Comparison (e.g. "Sony vs Bose headphones"): vector=0.7, bm25=0.3, type=semantic
- Availability (e.g. "is XM5 in stock"): vector=0.3, bm25=0.7, type=keyword
- General/unclear: vector=0.5, bm25=0.5, type=balanced

BM25 QUERY RULES (most important for search accuracy):
- If query contains a brand or model name AND category noise words: strip the category/intent words
  Examples:
    "gopro brand mobile" → bm25_query: "gopro"
    "sony er headphone"  → bm25_query: "sony headphone"
    "nike brand shoe"    → bm25_query: "nike"
    "apple laptop dekhao"→ bm25_query: "apple laptop"
- If query has NO brand/model: keep meaningful content words, strip filler only
  Examples:
    "best wireless headphones under 5000" → bm25_query: "wireless headphones"
    "noise cancelling earbuds"            → bm25_query: "noise cancelling earbuds"
    "gaming mouse"                        → bm25_query: "gaming mouse"
- Never return empty bm25_query — fallback to the original query if unsure

INTENT RULES:
- exact_lookup: specific model codes, SKUs, alphanumeric product IDs
- recommendation: best, suggest, recommend, top, ideal, valo (Bengali: good)
- comparison: vs, versus, compare, difference, better, between
- price_filter: under, below, above, over, budget, taka, tk, $, cheap, sosta (Bengali: cheap)
- availability: in stock, available, ache ki (Bengali: is it there), pabo (Bengali: will get)
- feature_search: specific features like wireless, ANC, waterproof, battery life
- browse: show all, list, display all, dekhao (Bengali: show)
- general: unclear or mixed intent
- off_topic: greetings, chitchat, questions unrelated to products or shopping
  Examples: "hi", "how are you", "what is AI", "tell me a joke", "who are you"
  Use off_topic when the query has NO connection to product search, browsing, or e-commerce

FILTER EXTRACTION RULES:
- brand: only if a specific brand is explicitly mentioned ("Sony", "Nike", "GoPro")
  Do NOT extract brand from generic words ("mobile brand" → brand: null)
- price: extract numeric value, convert currency mentions to number
  "5000 taka" → price_max: 5000
  "under $100" → price_max: 100
  "between 500 and 1000" → price_min: 500, price_max: 1000
- status: only if explicitly mentioned (active, discontinued, available)
- is_banglish: true if query contains Bengali script or Banglish romanized Bengali
- is_size_query: true if query contains size tokens (S, M, L, XL, XXL, small, medium, large)
- is_brand_query: true if a specific brand name is present in the query

Return ONLY the JSON object, no explanation.\
"""


_classifier_client: AsyncOpenAI | None = None


def _get_classifier_client() -> AsyncOpenAI:
    global _classifier_client
    if _classifier_client is None:
        _classifier_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _classifier_client


def _parse_intent(value: Any) -> Intent:
    try:
        return Intent(str(value))
    except ValueError:
        return Intent.GENERAL


def _parse_query_type(value: Any) -> QueryType:
    try:
        return QueryType(str(value))
    except ValueError:
        return QueryType.BALANCED


def _parse_llm_response(raw: str, original_query: str) -> ClassificationResult:
    cleaned = raw.replace("```json", "").replace("```", "").strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("Classifier LLM returned invalid JSON: %r", raw[:200])
        return _fallback_classify(original_query)

    vector_weight = float(data.get("vector_weight", 0.5))
    bm25_weight   = float(data.get("bm25_weight",   0.5))

    total = vector_weight + bm25_weight
    if total > 0:
        vector_weight /= total
        bm25_weight   /= total
    else:
        vector_weight = bm25_weight = 0.5

    primary_intent = _parse_intent(data.get("primary_intent", "general"))

    raw_secondary = data.get("secondary_intents", [])
    secondary_intents = [
        _parse_intent(i) for i in (raw_secondary or [])
        if _parse_intent(i) != primary_intent
    ]

    bm25_query = str(data.get("bm25_query") or original_query).strip()
    if not bm25_query:
        bm25_query = original_query

    price_max = data.get("price_max")
    price_min = data.get("price_min")
    brand     = data.get("brand")
    status    = data.get("status")

    try:
        price_max = float(price_max) if price_max is not None else None
    except (TypeError, ValueError):
        price_max = None

    try:
        price_min = float(price_min) if price_min is not None else None
    except (TypeError, ValueError):
        price_min = None

    if brand is not None and str(brand).strip().lower() in ("", "null", "none"):
        brand = None

    if status is not None and str(status).strip().lower() in ("", "null", "none"):
        status = None

    return ClassificationResult(
        vector_weight     = round(vector_weight, 3),
        bm25_weight       = round(bm25_weight, 3),
        query_type        = _parse_query_type(data.get("query_type", "balanced")),
        intent            = primary_intent,
        intent_confidence = round(min(float(data.get("intent_confidence", 0.5)), 1.0), 2),
        secondary_intents = secondary_intents,
        bm25_query        = bm25_query,
        price_max         = price_max,
        price_min         = price_min,
        brand             = brand,
        status            = status,
        is_banglish       = bool(data.get("is_banglish", False)),
        is_size_query     = bool(data.get("is_size_query", False)),
        is_brand_query    = bool(data.get("is_brand_query", False)),
    )


async def classify_and_extract(query: str) -> ClassificationResult:
    if not query or not query.strip():
        raise ValueError("query must be a non-empty, non-whitespace string")

    prompt = _CLASSIFY_PROMPT.format(query=query)

    try:
        client = _get_classifier_client()
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=300,
            timeout=8.0,
        )
        raw = response.choices[0].message.content.strip()
        result = _parse_llm_response(raw, query)

        logger.info(
            "Classifier | query=%r | intent=%s | type=%s | "
            "weights=(v=%.2f, b=%.2f) | bm25_query=%r | "
            "brand=%s | price_min=%s | price_max=%s | banglish=%s",
            query,
            result.intent,
            result.query_type,
            result.vector_weight,
            result.bm25_weight,
            result.bm25_query,
            result.brand,
            result.price_min,
            result.price_max,
            result.is_banglish,
        )
        return result

    except Exception:
        logger.warning(
            "Classifier LLM failed for query=%r — using rule-based fallback",
            query,
            exc_info=True,
        )
        return _fallback_classify(query)


_FB_CODE_RE      = re.compile(r"\b([A-Z]{1,5}-\d[\w-]*|[A-Z]{2,5}\d{3,}[A-Z\d]*|\d{3,}[A-Z]{1,5})\b")
_FB_QUESTION_RE  = re.compile(r"^(what|which|who|how|where|when|why|is|are|can|should)\b", re.IGNORECASE)
_FB_RECOMMEND_RE = re.compile(r"\b(suggest|recommend|best|top|ideal|perfect|suitable|looking for)\b", re.IGNORECASE)
_FB_COMPARE_RE   = re.compile(r"\b(vs|versus|compare|difference|better|between)\b", re.IGNORECASE)
_FB_PRICE_RE     = re.compile(r"\b(under|below|above|over|between|price|cost|taka|tk|\$|budget|cheap|affordable)\b", re.IGNORECASE)
_FB_BROWSE_RE    = re.compile(r"^(show|list|display|all|browse|see all|find all|give me all)\b", re.IGNORECASE)
_FB_FEATURE_RE   = re.compile(r"\b(with|without|has|support|feature|waterproof|wireless|bluetooth|usb|hdmi|anc|noise.cancell?ing)\b", re.IGNORECASE)
_FB_OFFTOPIC_RE = re.compile(
    r"^(hi|hello|hey|howdy|greetings|good (morning|afternoon|evening|night)|"
    r"how are you|what('s| is) up|who are you|what are you|tell me a joke|"
    r"thanks|thank you|bye|goodbye|ok|okay|yes|no|sure|nice|cool|great|lol)\b.*$",
    re.IGNORECASE,
)


def _fallback_classify(query: str) -> ClassificationResult:
    q       = query.strip()
    tokens  = q.split()
    n       = len(tokens)
    if _FB_OFFTOPIC_RE.match(q) or (n <= 3 and not has_code and not has_price and not has_feature and intent == Intent.GENERAL and confidence <= 0.30):
        return ClassificationResult(
            vector_weight=0.5, bm25_weight=0.5,
            query_type=QueryType.BALANCED,
            intent=Intent.OFF_TOPIC,
            intent_confidence=0.95,
            secondary_intents=[],
            bm25_query=query,
        )
    has_code     = bool(_FB_CODE_RE.search(q))
    is_question  = bool(_FB_QUESTION_RE.match(q))
    has_recommend= bool(_FB_RECOMMEND_RE.search(q))
    has_compare  = bool(_FB_COMPARE_RE.search(q))
    has_price    = bool(_FB_PRICE_RE.search(q))
    is_browse    = bool(_FB_BROWSE_RE.match(q))
    has_feature  = bool(_FB_FEATURE_RE.search(q))
    has_digits   = bool(re.search(r"\d", q))

    if has_compare:
        intent, confidence = Intent.COMPARISON, 0.75
    elif has_price:
        intent, confidence = Intent.PRICE_FILTER, 0.70
    elif is_browse:
        intent, confidence = Intent.BROWSE, 0.75
    elif has_recommend:
        intent, confidence = Intent.RECOMMENDATION, 0.70
    elif has_code:
        intent, confidence = Intent.EXACT_LOOKUP, 0.80
    elif has_feature:
        intent, confidence = Intent.FEATURE_SEARCH, 0.60
    else:
        intent, confidence = Intent.GENERAL, 0.30

    score = 0
    if n <= 2:   score += 2
    elif n <= 4: score += 1
    if has_code:   score += 2
    if has_digits: score += 1
    if is_question: score -= 2
    if n >= 8:   score -= 1

    if score >= 2:
        weights = WEIGHTS_EXACT if intent == Intent.EXACT_LOOKUP else WEIGHTS_KEYWORD
    elif score <= -2:
        weights = WEIGHTS_SEMANTIC
    else:
        if intent in (Intent.RECOMMENDATION, Intent.BROWSE, Intent.COMPARISON):
            weights = WEIGHTS_SEMANTIC
        else:
            weights = WEIGHTS_BALANCED

    return ClassificationResult(
        vector_weight     = weights.vector,
        bm25_weight       = weights.bm25,
        query_type        = weights.query_type,
        intent            = intent,
        intent_confidence = confidence,
        secondary_intents = [],
        bm25_query        = query,
        price_max         = None,
        price_min         = None,
        brand             = None,
        status            = None,
        is_banglish       = False,
        is_size_query     = False,
        is_brand_query    = False,
    )


def classify_query(query: str) -> QueryClassification:
    import warnings
    warnings.warn(
        "classify_query() is deprecated. Use classify_and_extract() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    result = _fallback_classify(query)
    return result.to_query_classification()