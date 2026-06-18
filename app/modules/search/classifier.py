from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple


class QueryType(str, Enum):
    KEYWORD = "keyword"
    SEMANTIC = "semantic"
    BALANCED = "balanced"


class Intent(str, Enum):
    EXACT_LOOKUP = "exact_lookup"
    RECOMMENDATION = "recommendation"
    COMPARISON = "comparison"
    PRICE_FILTER = "price_filter"
    AVAILABILITY = "availability"
    FEATURE_SEARCH = "feature_search"
    BROWSE = "browse"
    GENERAL = "general"


class _Weights(NamedTuple):
    vector: float
    bm25: float
    query_type: QueryType


WEIGHTS_KEYWORD = _Weights(vector=0.2, bm25=0.8, query_type=QueryType.KEYWORD)
WEIGHTS_SEMANTIC = _Weights(vector=0.8, bm25=0.2, query_type=QueryType.SEMANTIC)
WEIGHTS_BALANCED = _Weights(vector=0.5, bm25=0.5, query_type=QueryType.BALANCED)
WEIGHTS_EXACT = _Weights(vector=0.1, bm25=0.9, query_type=QueryType.KEYWORD)

_INTENT_WEIGHT_OVERRIDES: dict[Intent, _Weights] = {
    Intent.EXACT_LOOKUP: WEIGHTS_EXACT,
    Intent.RECOMMENDATION: WEIGHTS_SEMANTIC,
    Intent.BROWSE: WEIGHTS_SEMANTIC,
}

_KEYWORD_SCORE_THRESHOLD = 2
_SEMANTIC_SCORE_THRESHOLD = -2


@dataclass(frozen=True)
class QueryClassification:
    vector_weight: float
    bm25_weight: float
    query_type: QueryType
    intent: Intent
    intent_confidence: float


_CODE_RE = re.compile(
    r"\b("
    r"[A-Z]{1,5}-\d[\w-]*"
    r"|[A-Z]{2,5}\d{3,}[A-Z\d]*"
    r"|\d{3,}[A-Z]{1,5}"
    r")\b"
)

_ALLCAPS_RE = re.compile(r"\b[A-Z]{3,}\b")
_QUESTION_RE = re.compile(
    r"^(what|which|who|how|where|when|why|is|are|can|should)\b",
    re.IGNORECASE,
)
_RECOMMEND_RE = re.compile(
    r"\b(suggest|recommend|best|top|ideal|perfect|suitable|looking for)\b",
    re.IGNORECASE,
)
_COMPARE_RE = re.compile(
    r"\b(vs|versus|compare|difference|better|between)\b",
    re.IGNORECASE,
)
_PRICE_RE = re.compile(
    r"\b(under|below|above|over|between|price|cost|taka|tk|\$|budget|cheap|affordable|expensive|premium)\b",
    re.IGNORECASE,
)
_AVAILABILITY_RE = re.compile(
    r"\b(in stock|available|availability|stock|do you have|got)\b",
    re.IGNORECASE,
)
_FEATURE_RE = re.compile(
    r"\b(with|without|has|support|feature|waterproof|wireless|bluetooth|usb|hdmi|anc|noise.cancell?ing)\b",
    re.IGNORECASE,
)
_BROWSE_RE = re.compile(
    r"^(show|list|display|all|browse|see all|find all|give me all)\b",
    re.IGNORECASE,
)

_NEUTRAL_FILLER: frozenset[str] = frozenset(
    {
        "the",
        "a",
        "an",
        "for",
        "me",
        "my",
        "some",
        "any",
        "something",
        "anything",
        "and",
        "but",
        "that",
        "this",
        "those",
        "these",
        "daily",
        "use",
        "using",
    }
)


def _filler_ratio(tokens: list[str]) -> float:
    if not tokens:
        return 0.0
    return sum(1 for t in tokens if t.lower() in _NEUTRAL_FILLER) / len(tokens)


def _unique_token_ratio(tokens: list[str]) -> float:
    if not tokens:
        return 0.0
    return len({t.lower() for t in tokens}) / len(tokens)


def _has_digits(query: str) -> bool:
    return bool(re.search(r"\d", query))


def _has_product_hyphen(query: str) -> bool:
    return bool(
        re.search(
            r"\b[A-Za-z]+-\d[\w-]*\b|\b\d[\w]*-[A-Za-z\d]+\b",
            query,
        )
    )


@dataclass(frozen=True)
class _Signals:
    tokens: list[str]
    codes: list[str]
    allcaps: list[str]
    has_digits: bool
    has_prod_hyphen: bool
    is_question: bool
    has_recommend: bool
    has_compare: bool
    has_price: bool
    has_availability: bool
    has_feature: bool
    is_browse: bool
    filler_ratio: float
    unique_ratio: float


def _build_signals(query: str) -> _Signals:
    tokens = query.strip().split()
    return _Signals(
        tokens=tokens,
        codes=_CODE_RE.findall(query),
        allcaps=_ALLCAPS_RE.findall(query),
        has_digits=_has_digits(query),
        has_prod_hyphen=_has_product_hyphen(query),
        is_question=bool(_QUESTION_RE.match(query.strip())),
        has_recommend=bool(_RECOMMEND_RE.search(query)),
        has_compare=bool(_COMPARE_RE.search(query)),
        has_price=bool(_PRICE_RE.search(query)),
        has_availability=bool(_AVAILABILITY_RE.search(query)),
        has_feature=bool(_FEATURE_RE.search(query)),
        is_browse=bool(_BROWSE_RE.match(query.strip())),
        filler_ratio=_filler_ratio(tokens),
        unique_ratio=_unique_token_ratio(tokens),
    )


def _detect_intent(s: _Signals) -> tuple[Intent, float]:
    scores: dict[Intent, float] = {intent: 0.0 for intent in Intent}

    if s.codes:
        scores[Intent.EXACT_LOOKUP] += 0.60
    if s.allcaps and len(s.tokens) <= 3:
        scores[Intent.EXACT_LOOKUP] += 0.30

    if s.has_availability:
        scores[Intent.AVAILABILITY] += 0.70
    if s.is_question:
        scores[Intent.AVAILABILITY] += 0.10

    if s.has_compare:
        scores[Intent.COMPARISON] += 0.75

    if s.has_price:
        scores[Intent.PRICE_FILTER] += 0.70
    if s.has_digits:
        scores[Intent.PRICE_FILTER] += 0.10

    if s.is_browse:
        scores[Intent.BROWSE] += 0.75

    if s.has_recommend:
        scores[Intent.RECOMMENDATION] += 0.70
    if s.is_question:
        scores[Intent.RECOMMENDATION] += 0.10

    if s.has_feature:
        scores[Intent.FEATURE_SEARCH] += 0.60
    if not s.codes and not s.is_browse and not s.has_recommend:
        scores[Intent.FEATURE_SEARCH] += 0.10

    scores[Intent.GENERAL] = 0.30

    best_intent = max(scores, key=lambda i: scores[i])
    confidence = min(scores[best_intent], 1.0)

    return best_intent, round(confidence, 2)


def _compute_keyword_score(s: _Signals) -> int:
    n = len(s.tokens)
    score = 0

    if n <= 2:
        score += 2
    elif n <= 4:
        score += 1

    if s.codes:
        score += 2
    if s.allcaps:
        score += 1
    if s.has_digits:
        score += 1
    if s.has_prod_hyphen:
        score += 1

    if s.is_question:
        score -= 2
    if s.filler_ratio > 0.4:
        score -= 1
    if n >= 8:
        score -= 1
    if s.unique_ratio > 0.85 and n >= 5:
        score -= 1

    return score


def _classify_weights(s: _Signals) -> _Weights:
    score = _compute_keyword_score(s)

    if score >= _KEYWORD_SCORE_THRESHOLD:
        return WEIGHTS_KEYWORD

    if score <= _SEMANTIC_SCORE_THRESHOLD:
        return WEIGHTS_SEMANTIC

    return WEIGHTS_BALANCED


def classify_query(query: str) -> QueryClassification:
    if not query or not query.strip():
        raise ValueError("query must be a non-empty, non-whitespace string")

    signals = _build_signals(query)
    weights = _classify_weights(signals)
    intent, confidence = _detect_intent(signals)

    final_weights = _INTENT_WEIGHT_OVERRIDES.get(intent, weights)

    return QueryClassification(
        vector_weight=final_weights.vector,
        bm25_weight=final_weights.bm25,
        query_type=final_weights.query_type,
        intent=intent,
        intent_confidence=confidence,
    )