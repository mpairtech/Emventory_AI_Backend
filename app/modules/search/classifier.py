"""
Query classifier for hybrid search weight selection.

Domain-agnostic — uses only linguistic signals, no hardcoded
product terms. Works across all org types (clothing, electronics,
cosmetics, jewelry, stationery, etc.).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class QueryWeights:
    vector_weight: float
    bm25_weight: float
    query_type: str  # "semantic" | "keyword" | "balanced"


# ---------------------------------------------------------------------------
# Linguistic signal detectors  (pure functions, no domain knowledge)
# ---------------------------------------------------------------------------

# Tokens that look like product codes / model numbers / SKUs
_CODE_PATTERN = re.compile(
    r"""
    \b(
        [A-Z]{1,5}\d{2,}       |   # S24, XM5, RTX4070
        \d{2,}[A-Z]{1,5}       |   # 4070Ti
        [A-Z]+-\d+[\w-]*       |   # WH-1000XM5, XPS-15
        [A-Z]{2,}\d+[A-Z]*     |   # IP68, USB3C
        \d+[A-Z]{1,3}\b            # 256GB, 12MP, 5000mAh
    )\b
    """,
    re.VERBOSE,
)

# All-caps words that are likely attributes/codes (XL, USB, HDMI, SKU)
_ALLCAPS_PATTERN = re.compile(r"\b[A-Z]{2,}\b")

# Question / intent patterns → semantic
_QUESTION_PATTERN = re.compile(
    r"^(what|which|who|how|where|when|why|is|are|can|should|suggest|recommend|help|find|show|give)\b",
    re.IGNORECASE,
)

# Natural language filler words → semantic
_FILLER_WORDS = frozenset({
    "the", "a", "an", "for", "me", "my", "some", "any", "good",
    "best", "nice", "great", "something", "anything", "with", "and",
    "or", "but", "that", "this", "those", "these", "need", "want",
    "looking", "suggest", "recommend", "daily", "use", "using",
    "budget", "affordable", "cheap", "expensive", "premium",
})


def _count_code_tokens(query: str) -> int:
    return len(_CODE_PATTERN.findall(query))


def _count_allcaps_tokens(query: str) -> int:
    return len(_ALLCAPS_PATTERN.findall(query))


def _token_count(query: str) -> int:
    return len(query.split())


def _filler_ratio(tokens: list[str]) -> float:
    if not tokens:
        return 0.0
    filler = sum(1 for t in tokens if t.lower() in _FILLER_WORDS)
    return filler / len(tokens)


def _has_digits(query: str) -> bool:
    return bool(re.search(r"\d", query))


def _has_hyphenated_term(query: str) -> bool:
    return bool(re.search(r"\b\w+-\w+\b", query))


def _is_question(query: str) -> bool:
    return bool(_QUESTION_PATTERN.match(query.strip()))


def _unique_token_ratio(tokens: list[str]) -> float:
    """High ratio = many distinct words = more natural language."""
    if not tokens:
        return 0.0
    return len(set(t.lower() for t in tokens)) / len(tokens)


# ---------------------------------------------------------------------------
# Main classifier
# ---------------------------------------------------------------------------

def classify_query(query: str) -> QueryWeights:
    """
    Classify query into search weights using linguistic signals only.

    Returns (vector_weight, bm25_weight) where both sum to 1.0.

    Signal scoring:
      BM25 signals  → short query, digits, codes, allcaps, hyphens
      Vector signals → question form, high filler ratio, long query

    Scale: each signal contributes ±1 to a score.
    Score < -1  → semantic dominant  (0.8 vector, 0.2 bm25)
    Score -1..1 → balanced           (0.5 vector, 0.5 bm25)
    Score > 1   → keyword dominant   (0.2 vector, 0.8 bm25)
    """
    if not query or not query.strip():
        return QueryWeights(0.5, 0.5, "balanced")

    q = query.strip()
    tokens = q.split()
    n = len(tokens)
    filler_r = _filler_ratio(tokens)
    unique_r = _unique_token_ratio(tokens)
    codes = _count_code_tokens(q)
    allcaps = _count_allcaps_tokens(q)

    score = 0  # positive → BM25, negative → vector

    # --- BM25 signals ---
    if n <= 2:
        score += 2          # very short → almost certainly keyword
    elif n <= 4:
        score += 1          # short → lean BM25

    if codes >= 1:
        score += 2          # model numbers / SKUs → BM25 critical
    if allcaps >= 1:
        score += 1          # XL, USB, HDMI etc.
    if _has_digits(q):
        score += 1          # numeric specs, prices, model numbers
    if _has_hyphenated_term(q):
        score += 1          # WH-1000XM5, in-stock etc.

    # --- Vector signals ---
    if _is_question(q):
        score -= 2          # "suggest me...", "what is best..." → semantic
    if filler_r > 0.4:
        score -= 2          # lots of filler → natural language → semantic
    if n >= 8:
        score -= 1          # long query → natural language
    if unique_r > 0.85 and n >= 5:
        score -= 1          # many distinct words → conversational

    # --- Map score to weights ---
    if score >= 2:
        return QueryWeights(0.2, 0.8, "keyword")
    elif score <= -2:
        return QueryWeights(0.8, 0.2, "semantic")
    else:
        return QueryWeights(0.5, 0.5, "balanced")