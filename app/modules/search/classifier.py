"""
Query classifier for hybrid search pipeline.

Detects:
1. Query type (keyword / semantic / balanced) -> BM25 vs vector weights
2. Intent type -> informs filter builder and reranker behavior

Domain-agnostic -- pure linguistic signals, no hardcoded product terms.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class QueryClassification:
    vector_weight: float
    bm25_weight: float
    query_type: str          # "semantic" | "keyword" | "balanced"
    intent: str              # see INTENT_* constants below
    intent_confidence: float # 0.0 - 1.0


# ---------------------------------------------------------------------------
# Intent constants
# ---------------------------------------------------------------------------

INTENT_EXACT_LOOKUP   = "exact_lookup"    # "Sony WF-1000XM5 price"
INTENT_RECOMMENDATION = "recommendation"  # "suggest me a good laptop"
INTENT_COMPARISON     = "comparison"      # "difference between X and Y"
INTENT_PRICE_FILTER   = "price_filter"    # "laptops under $500"
INTENT_AVAILABILITY   = "availability"    # "is X in stock"
INTENT_FEATURE_SEARCH = "feature_search"  # "waterproof earbuds with ANC"
INTENT_BROWSE         = "browse"          # "show me all laptops"
INTENT_GENERAL        = "general"         # fallback


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

_CODE_PATTERN = re.compile(
    r"""\b([A-Z]{1,5}\d{2,}|\d{2,}[A-Z]{1,5}|[A-Z]+-\d+[\w-]*|[A-Z]{2,}\d+[A-Z]*|\d+[A-Z]{1,3})\b""",
    re.VERBOSE,
)
_ALLCAPS_PATTERN      = re.compile(r"\b[A-Z]{2,}\b")
_QUESTION_PATTERN     = re.compile(r"^(what|which|who|how|where|when|why|is|are|can|should)\b", re.IGNORECASE)
_RECOMMEND_PATTERN    = re.compile(r"\b(suggest|recommend|best|good|top|ideal|perfect|suitable|help|need|want|looking)\b", re.IGNORECASE)
_COMPARE_PATTERN      = re.compile(r"\b(vs|versus|compare|difference|better|between|or)\b", re.IGNORECASE)
_PRICE_PATTERN        = re.compile(r"\b(under|below|above|over|between|cheap|budget|affordable|expensive|premium|price|cost|taka|tk|\$)\b", re.IGNORECASE)
_AVAILABILITY_PATTERN = re.compile(r"\b(in stock|available|stock|availability|have|got|exist)\b", re.IGNORECASE)
_FEATURE_PATTERN      = re.compile(r"\b(with|without|has|have|support|feature|waterproof|wireless|bluetooth|usb|hdmi|anc|noise)\b", re.IGNORECASE)
_BROWSE_PATTERN       = re.compile(r"^(show|list|display|give me all|all|browse|see all|find all)\b", re.IGNORECASE)

_FILLER_WORDS = frozenset({
    "the", "a", "an", "for", "me", "my", "some", "any", "good", "best",
    "nice", "great", "something", "anything", "with", "and", "or", "but",
    "that", "this", "those", "these", "need", "want", "looking", "suggest",
    "recommend", "daily", "use", "using", "budget", "affordable", "cheap",
    "expensive", "premium",
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _filler_ratio(tokens: list[str]) -> float:
    if not tokens:
        return 0.0
    return sum(1 for t in tokens if t.lower() in _FILLER_WORDS) / len(tokens)


def _unique_token_ratio(tokens: list[str]) -> float:
    if not tokens:
        return 0.0
    return len(set(t.lower() for t in tokens)) / len(tokens)


def _has_digits(query: str) -> bool:
    return bool(re.search(r"\d", query))


def _has_hyphenated_term(query: str) -> bool:
    return bool(re.search(r"\b\w+-\w+\b", query))


# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------

def _detect_intent(query: str) -> tuple[str, float]:
    q = query.strip()

    codes   = _CODE_PATTERN.findall(q)
    allcaps = _ALLCAPS_PATTERN.findall(q)
    if codes or (allcaps and len(q.split()) <= 4):
        return INTENT_EXACT_LOOKUP, 0.90

    if _AVAILABILITY_PATTERN.search(q):
        return INTENT_AVAILABILITY, 0.85

    if _COMPARE_PATTERN.search(q):
        return INTENT_COMPARISON, 0.85

    if _PRICE_PATTERN.search(q):
        return INTENT_PRICE_FILTER, 0.80

    if _BROWSE_PATTERN.match(q):
        return INTENT_BROWSE, 0.80

    if _RECOMMEND_PATTERN.search(q):
        return INTENT_RECOMMENDATION, 0.75

    if _FEATURE_PATTERN.search(q):
        return INTENT_FEATURE_SEARCH, 0.70

    return INTENT_GENERAL, 0.50


# ---------------------------------------------------------------------------
# Weight classification
# ---------------------------------------------------------------------------

def _classify_weights(query: str) -> tuple[float, float, str]:
    tokens = query.strip().split()
    n      = len(tokens)

    score = 0

    if n <= 2:        score += 2
    elif n <= 4:      score += 1
    if _CODE_PATTERN.findall(query):               score += 2
    if _ALLCAPS_PATTERN.findall(query):            score += 1
    if _has_digits(query):                         score += 1
    if _has_hyphenated_term(query):                score += 1
    if _QUESTION_PATTERN.match(query.strip()):     score -= 2
    if _filler_ratio(tokens) > 0.4:               score -= 2
    if n >= 8:                                     score -= 1
    if _unique_token_ratio(tokens) > 0.85 and n >= 5: score -= 1

    if score >= 2:    return 0.2, 0.8, "keyword"
    elif score <= -2: return 0.8, 0.2, "semantic"
    else:             return 0.5, 0.5, "balanced"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def classify_query(query: str) -> QueryClassification:
    if not query or not query.strip():
        return QueryClassification(0.5, 0.5, "balanced", INTENT_GENERAL, 0.0)

    vector_w, bm25_w, q_type = _classify_weights(query)
    intent, confidence        = _detect_intent(query)

    # Intent overrides weights
    if intent == INTENT_EXACT_LOOKUP:
        vector_w, bm25_w, q_type = 0.1, 0.9, "keyword"
    elif intent in (INTENT_RECOMMENDATION, INTENT_BROWSE):
        vector_w, bm25_w, q_type = 0.8, 0.2, "semantic"

    return QueryClassification(
        vector_weight=vector_w,
        bm25_weight=bm25_w,
        query_type=q_type,
        intent=intent,
        intent_confidence=confidence,
    )