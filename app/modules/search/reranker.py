"""
LLM Reranker using gpt-4o-mini.

Scores each retrieved product against the query for true relevance,
eliminating false positives that slip through hybrid retrieval.

Design:
- Batch all candidates in ONE API call (not one call per product)
- Returns scored + filtered results above threshold
- Falls back to original order if reranker fails
"""

from __future__ import annotations

import copy
import json
import logging
import time
from typing import Any

from openai import AsyncOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

_reranker_client: AsyncOpenAI | None = None

_DESC_LIMIT = 150
_SPEC_LIMIT = 100
_SCORE_BUFFER_PER_CANDIDATE = 10
_SCORE_BUFFER_BASE = 50

_INTENT_NOTES: dict[str, str] = {
    "exact_lookup":   "Exact model/brand match is most important.",
    "recommendation": "Overall fit for the user's need is most important.",
    "comparison":     "Products that match the comparison criteria are most relevant.",
    "price_filter":   "Price range fit is critical — penalize out-of-range products.",
    "availability":   "Stock status is important.",
    "feature_search": "Specific feature match is most important.",
    "browse":         "Category/type match is most important.",
    "general":        "Overall relevance to the query.",
}

_RERANK_PROMPT_TEMPLATE = """\
You are a product search relevance judge.

User query: "{query}"
Scoring note: {intent_note}

Rate each product's relevance to the query on a scale of 0.0 to 1.0:
- 1.0 = Perfect match, exactly what the user wants
- 0.7 = Good match, mostly relevant
- 0.4 = Partial match, somewhat relevant
- 0.1 = Poor match, barely relevant
- 0.0 = Irrelevant, completely unrelated

Products:
{products_text}

Return ONLY a JSON array of scores in the same order as the products.
Example for 3 products: [0.9, 0.3, 0.1]
No explanation, just the JSON array.\
"""


def _get_reranker_client() -> AsyncOpenAI:
    global _reranker_client
    if _reranker_client is None:
        _reranker_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _reranker_client


def _build_product_summary(index: int, product: dict[str, Any]) -> str:
    parts = [f"[{index}] {product.get('name', 'Unknown')}"]
    if product.get("category"):
        parts.append(f"Category: {product['category']}")
    if product.get("brand"):
        parts.append(f"Brand: {product['brand']}")
    if product.get("price"):
        parts.append(f"Price: ${product['price']}")
    if product.get("description"):
        desc = product["description"]
        truncated = desc[:_DESC_LIMIT]
        parts.append(truncated + ("..." if len(desc) > _DESC_LIMIT else ""))
    if product.get("specifications"):
        spec = product["specifications"]
        truncated = spec[:_SPEC_LIMIT]
        parts.append(f"Specs: {truncated}" + ("..." if len(spec) > _SPEC_LIMIT else ""))
    return " | ".join(parts)


def _build_prompt(query: str, candidates: list[dict[str, Any]], intent: str) -> str:
    intent_note = _INTENT_NOTES.get(intent, _INTENT_NOTES["general"])
    products_text = "\n".join(
        _build_product_summary(i, p) for i, p in enumerate(candidates)
    )
    return _RERANK_PROMPT_TEMPLATE.format(
        query=query,
        intent_note=intent_note,
        products_text=products_text,
    )


def _parse_scores(raw: str) -> list[float] | None:
    cleaned = raw.replace("```json", "").replace("```", "").strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list):
        return None
    return parsed


def _score_to_float(score: Any, index: int) -> float:
    try:
        return float(score)
    except (TypeError, ValueError):
        logger.warning("Reranker returned non-numeric score at index %d: %r — defaulting to 0.0", index, score)
        return 0.0


async def rerank(
    query: str,
    candidates: list[dict[str, Any]],
    top_k: int = 5,
    threshold: float = 0.4,
    intent: str = "general",
) -> list[dict[str, Any]]:
    """
    Rerank candidates using gpt-4o-mini relevance scoring.

    Args:
        query: Original user query.
        candidates: Products from hybrid retrieval.
        top_k: Max results to return after reranking.
        threshold: Minimum relevance score (0.0–1.0) to keep a result.
        intent: Query intent from classifier (adjusts scoring prompt).

    Returns:
        Reranked and filtered list, best first.
        Falls back to candidates[:top_k] if the LLM call fails.
        The fallback does not apply threshold filtering.
    """
    if not candidates:
        return []

    if len(candidates) == 1:
        result = copy.deepcopy(candidates[0])
        result["rerank_score"] = None
        return [result]

    prompt = _build_prompt(query, candidates, intent)
    max_tokens = len(candidates) * _SCORE_BUFFER_PER_CANDIDATE + _SCORE_BUFFER_BASE

    t0 = time.monotonic()
    try:
        client = _get_reranker_client()
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=max_tokens,
            timeout=10.0,
        )
        elapsed = time.monotonic() - t0

        usage = response.usage
        logger.info(
            "Reranker API | latency=%.3fs | prompt_tokens=%d | completion_tokens=%d | total_tokens=%d",
            elapsed,
            usage.prompt_tokens if usage else -1,
            usage.completion_tokens if usage else -1,
            usage.total_tokens if usage else -1,
        )

        raw = response.choices[0].message.content.strip()
        scores = _parse_scores(raw)

        if scores is None or len(scores) != len(candidates):
            logger.warning(
                "Reranker returned unexpected format (scores=%r, expected_len=%d) — using original order",
                scores,
                len(candidates),
            )
            return candidates[:top_k]

        scored: list[tuple[float, dict[str, Any]]] = []
        for i, (product, score) in enumerate(zip(candidates, scores)):
            s = _score_to_float(score, i)
            if s >= threshold:
                enriched = copy.deepcopy(product)
                enriched["rerank_score"] = round(s, 3)
                scored.append((s, enriched))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = [p for _, p in scored[:top_k]]

        logger.info(
            "Reranker | query=%r | intent=%s | input=%d | passed=%d | top_k=%d",
            query,
            intent,
            len(candidates),
            len(results),
            top_k,
        )
        return results

    except Exception:
        elapsed = time.monotonic() - t0
        logger.warning(
            "Reranker failed after %.3fs — using original order (threshold not applied)",
            elapsed,
            exc_info=True,
        )
        return candidates[:top_k]