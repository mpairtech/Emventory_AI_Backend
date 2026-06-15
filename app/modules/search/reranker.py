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

import json
import logging
from typing import Any, Dict, List

from openai import AsyncOpenAI
from app.core.config import settings

logger = logging.getLogger(__name__)

_reranker_client: AsyncOpenAI | None = None


def _get_reranker_client() -> AsyncOpenAI:
    global _reranker_client
    if _reranker_client is None:
        _reranker_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _reranker_client


async def rerank(
    query: str,
    candidates: List[Dict[str, Any]],
    top_k: int = 5,
    threshold: float = 0.4,
    intent: str = "general",
) -> List[Dict[str, Any]]:
    """
    Rerank candidates using gpt-4o-mini relevance scoring.

    Args:
        query: Original user query
        candidates: Products from hybrid retrieval
        top_k: Max results to return after reranking
        threshold: Minimum relevance score (0.0-1.0) to keep a result
        intent: Query intent from classifier (adjusts scoring prompt)

    Returns:
        Reranked and filtered list, best first.
        Falls back to original order if LLM call fails.
    """
    if not candidates:
        return []

    # If only 1 candidate, skip reranking
    if len(candidates) == 1:
        return candidates

    # Build compact product summaries for the prompt
    product_summaries = []
    for i, p in enumerate(candidates):
        parts = [f"[{i}] {p.get('name', 'Unknown')}"]
        if p.get("category"):
            parts.append(f"Category: {p['category']}")
        if p.get("brand"):
            parts.append(f"Brand: {p['brand']}")
        if p.get("price"):
            parts.append(f"Price: ${p['price']}")
        if p.get("description"):
            parts.append(f"{p['description'][:150]}")
        if p.get("specifications"):
            parts.append(f"Specs: {p['specifications'][:100]}")
        product_summaries.append(" | ".join(parts))

    products_text = "\n".join(product_summaries)

    # Intent-aware scoring instruction
    intent_note = {
        "exact_lookup":   "Exact model/brand match is most important.",
        "recommendation": "Overall fit for the user's need is most important.",
        "comparison":     "Products that match the comparison criteria are most relevant.",
        "price_filter":   "Price range fit is critical — penalize out-of-range products.",
        "availability":   "Stock status is important.",
        "feature_search": "Specific feature match is most important.",
        "browse":         "Category/type match is most important.",
        "general":        "Overall relevance to the query.",
    }.get(intent, "Overall relevance to the query.")

    prompt = f"""You are a product search relevance judge.

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
No explanation, just the JSON array."""

    try:
        client = _get_reranker_client()
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=200,
        )

        raw = response.choices[0].message.content.strip()
        # Strip markdown fences if present
        raw = raw.replace("```json", "").replace("```", "").strip()
        scores = json.loads(raw)

        if not isinstance(scores, list) or len(scores) != len(candidates):
            logger.warning("Reranker returned unexpected format, using original order")
            return candidates[:top_k]

        # Attach reranker scores and filter
        scored = []
        for product, score in zip(candidates, scores):
            try:
                s = float(score)
            except (TypeError, ValueError):
                s = 0.0
            if s >= threshold:
                product = dict(product)
                product["rerank_score"] = round(s, 3)
                scored.append((s, product))

        # Sort by reranker score descending
        scored.sort(key=lambda x: x[0], reverse=True)
        results = [p for _, p in scored[:top_k]]

        logger.info(
            "Reranker | query='%s' | intent=%s | input=%d | passed=%d | top_k=%d",
            query, intent, len(candidates), len(results), top_k,
        )
        return results

    except Exception as e:
        logger.warning("Reranker failed, using original order: %s", e)
        return candidates[:top_k]