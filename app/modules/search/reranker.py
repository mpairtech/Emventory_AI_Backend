"""
LLM Reranker using gpt-4o-mini.

Scores each retrieved product against the query for true relevance,
eliminating false positives that slip through hybrid retrieval.

Changes from previous version:
  - Added _resolve_price_ceiling() — derives budget ceiling from candidate
    price distribution. Works for any product category, no hardcoded values.
  - rerank() now accepts price_max, price_min, budget_qualifier params.
  - Intent note is enriched with resolved budget context before LLM call.
  - Post-LLM Python price penalty applied for products over budget ceiling.
  - _build_prompt() accepts intent_note override.
"""

from __future__ import annotations

import copy
import json
import logging
import time
from typing import Any, Optional

from openai import AsyncOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

_reranker_client: AsyncOpenAI | None = None

_DESC_LIMIT = 150
_SPEC_LIMIT = 100
_SCORE_BUFFER_PER_CANDIDATE = 10
_SCORE_BUFFER_BASE = 50

# Maximum score deduction for over-budget products (0.0 – 1.0)
_MAX_PRICE_PENALTY = 0.5

_INTENT_NOTES: dict[str, str] = {
    "exact_lookup":   "Exact model/brand match is most important.",
    "recommendation": (
        "The user wants a product specifically suited to their stated use case. "
        "Identify the use case from the query (e.g. 'gaming', 'hiking', 'professional photography', 'cooking'). "
        "Score 0.8–1.0 ONLY if the product's name, description, or specifications explicitly indicate "
        "it is designed or marketed for that exact use case. "
        "Score 0.3–0.5 for generic products that share some specs but are NOT purpose-built for the use case. "
        "Score 0.0–0.2 for products with no connection to the stated use case. "
        "Never reward shared specs alone — a generic product with good RAM is NOT a gaming product."
    ),
    "comparison":     "Products that match the comparison criteria are most relevant.",
    "price_filter":   "Price range fit is critical — penalize out-of-range products.",
    "availability":   "Stock status is important.",
    "feature_search": "Specific feature match is most important.",
    "browse":         "Category/type match is most important.",
    "general":        "Overall relevance to the query.",
}

_RERANK_PROMPT_TEMPLATE = """\
You are a product search relevance judge for an e-commerce platform.

User query: "{query}"
Scoring note: {intent_note}

Rate each product's relevance to the query on a scale of 0.0 to 1.0:
- 1.0 = Perfect match — explicitly designed or marketed for the user's stated need
- 0.7 = Good match — clearly relevant with strong supporting evidence in name, description, or specs
- 0.4 = Partial match — related category but NOT specifically designed for the stated use case
- 0.1 = Weak match — barely relevant
- 0.0 = Irrelevant — wrong category, or generic product with no explicit fit for stated need

UNIVERSAL SPECIFICITY RULE:
When the query expresses a specific use case, activity, profession, or purpose
(examples: gaming, hiking, nursing, cooking, photography, travel, running, construction),
apply this rule regardless of product category:
  - The product MUST explicitly serve that use case in its name, description, or specifications.
  - Shared specs alone do NOT qualify. Examples of what does NOT qualify:
      * A generic smartphone with 120Hz is NOT a gaming phone unless marketed as one.
      * A regular knife is NOT a chef knife unless described as professional/culinary.
      * A standard backpack is NOT a hiking pack unless designed for trail use.
      * A casual shoe is NOT a running shoe unless built for running.
  - If NO product in the list explicitly serves the stated use case, all scores must be below 0.4.
    Do NOT force a high score on the "closest" generic product.

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


def _build_prompt(
    query: str,
    candidates: list[dict[str, Any]],
    intent: str,
    intent_note: str | None = None,   # ← NEW: accepts override from rerank()
) -> str:
    note = intent_note or _INTENT_NOTES.get(intent, _INTENT_NOTES["general"])
    products_text = "\n".join(
        _build_product_summary(i, p) for i, p in enumerate(candidates)
    )
    return _RERANK_PROMPT_TEMPLATE.format(
        query=query,
        intent_note=note,
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
        logger.warning(
            "Reranker returned non-numeric score at index %d: %r — defaulting to 0.0",
            index, score,
        )
        return 0.0


# ── NEW: price ceiling resolution ─────────────────────────────────────────────

def _resolve_price_ceiling(
    candidates: list[dict[str, Any]],
    price_max: Optional[float],
    budget_qualifier: Optional[str],
) -> Optional[float]:
    """
    Resolve effective price ceiling from explicit price or budget qualifier.

    Explicit price_max always wins — it is a hard user constraint.

    budget_qualifier derives a soft ceiling from the candidate price
    distribution so the threshold self-adjusts to any product category:
      "tight" → bottom third  of candidate prices  (p33)
      "mid"   → bottom two-thirds of candidate prices (p66)
      "high"  → no ceiling applied

    Returns None when no ceiling can be determined.
    """
    # Hard constraint wins
    if price_max is not None:
        return price_max

    if budget_qualifier not in ("tight", "mid"):
        return None

    prices = sorted(
        float(p["price"])
        for p in candidates
        if p.get("price") and float(p.get("price") or 0) > 0
    )

    if not prices:
        return None

    n = len(prices)

    if budget_qualifier == "tight":
        idx = max(0, n // 3 - 1)
        return prices[idx]

    if budget_qualifier == "mid":
        idx = max(0, (2 * n) // 3 - 1)
        return prices[idx]

    return None


# ── NEW: budget-aware intent note builder ─────────────────────────────────────

def _build_budget_intent_note(
    base_intent: str,
    effective_ceiling: Optional[float],
    budget_qualifier: Optional[str],
    price_min: Optional[float],
) -> str:
    """
    Compose intent note for the reranker prompt, injecting budget context
    so the LLM scores products with price awareness.
    """
    note = _INTENT_NOTES.get(base_intent, _INTENT_NOTES["general"])

    if effective_ceiling is not None:
        note += (
            f" User budget ceiling is {effective_ceiling:.0f}. "
            f"Products priced above {effective_ceiling:.0f} should score LOWER. "
            f"Products at or below {effective_ceiling:.0f} should score HIGHER."
        )

    if budget_qualifier == "tight":
        note += (
            " User explicitly wants the most affordable option. "
            "Prefer lower-priced products that still meet the need. "
            "Do NOT score an expensive product highly just because it has more features."
        )
    elif budget_qualifier == "high":
        note += (
            " User wants the best quality regardless of price. "
            "Prefer premium, feature-rich products even if expensive."
        )

    if price_min is not None:
        note += (
            f" Minimum quality threshold: {price_min:.0f}. "
            f"Products below this price may not meet user expectations."
        )

    return note


# ─────────────────────────────────────────────────────────────────────────────

async def rerank(
    query: str,
    candidates: list[dict[str, Any]],
    top_k: int = 5,
    threshold: float = 0.4,
    intent: str = "general",
    price_max: Optional[float] = None,          # ← NEW
    price_min: Optional[float] = None,          # ← NEW
    budget_qualifier: Optional[str] = None,     # ← NEW
) -> list[dict[str, Any]]:
    """
    Rerank candidates using gpt-4o-mini relevance scoring.

    Args:
        query:            Original user query.
        candidates:       Products from hybrid retrieval.
        top_k:            Max results to return after reranking.
        threshold:        Minimum relevance score (0.0–1.0) to keep a result.
        intent:           Query intent from classifier.
        price_max:        Explicit price ceiling from classifier (wins over qualifier).
        price_min:        Explicit price floor from classifier.
        budget_qualifier: Qualitative budget signal: "tight" | "mid" | "high" | None.

    Returns:
        Reranked and filtered list, best first.
        Falls back to candidates[:top_k] if the LLM call fails.
    """
    if not candidates:
        return []

    if len(candidates) == 1:
        result = copy.deepcopy(candidates[0])
        result["rerank_score"] = None
        return [result]

    # ── Resolve price ceiling (pure Python, zero LLM cost) ───────────────
    effective_ceiling = _resolve_price_ceiling(candidates, price_max, budget_qualifier)

    if effective_ceiling is not None:
        logger.info(
            "Budget ceiling resolved | qualifier=%s | explicit_max=%s | ceiling=%.2f",
            budget_qualifier, price_max, effective_ceiling,
        )

    # ── Build intent note with budget context injected ────────────────────
    intent_note = _build_budget_intent_note(
        base_intent       = intent,
        effective_ceiling = effective_ceiling,
        budget_qualifier  = budget_qualifier,
        price_min         = price_min,
    )

    prompt = _build_prompt(query, candidates, intent, intent_note=intent_note)
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
            "Reranker API | latency=%.3fs | prompt_tokens=%d | "
            "completion_tokens=%d | total_tokens=%d",
            elapsed,
            usage.prompt_tokens if usage else -1,
            usage.completion_tokens if usage else -1,
            usage.total_tokens if usage else -1,
        )

        raw = response.choices[0].message.content.strip()
        scores = _parse_scores(raw)

        if scores is None or len(scores) != len(candidates):
            logger.warning(
                "Reranker returned unexpected format "
                "(scores=%r, expected_len=%d) — using original order",
                scores, len(candidates),
            )
            return candidates[:top_k]

        # ── Score products + apply Python price penalty ───────────────────
        scored: list[tuple[float, dict[str, Any]]] = []

        for i, (product, score) in enumerate(zip(candidates, scores)):
            s = _score_to_float(score, i)

            # Apply price penalty on top of LLM score (pure Python, zero cost)
            if effective_ceiling is not None:
                try:
                    product_price = float(product.get("price") or 0)
                    if product_price > 0 and product_price > effective_ceiling:
                        overage_ratio = (product_price - effective_ceiling) / effective_ceiling
                        penalty = min(0.3 * overage_ratio, _MAX_PRICE_PENALTY)
                        original_s = s
                        s = max(0.0, s - penalty)
                        logger.debug(
                            "Price penalty | product=%s | price=%.0f | "
                            "ceiling=%.0f | penalty=%.2f | score: %.2f→%.2f",
                            product.get("name"), product_price,
                            effective_ceiling, penalty, original_s, s,
                        )
                except (TypeError, ValueError):
                    pass

            if s >= threshold:
                enriched = copy.deepcopy(product)
                enriched["rerank_score"] = round(s, 3)
                scored.append((s, enriched))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = [p for _, p in scored[:top_k]]

        logger.info(
            "Reranker | query=%r | intent=%s | budget_qualifier=%s | "
            "ceiling=%s | input=%d | passed=%d | top_k=%d",
            query,
            intent,
            budget_qualifier,
            f"{effective_ceiling:.0f}" if effective_ceiling else "none",
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