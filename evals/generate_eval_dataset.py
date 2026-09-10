"""
generate_eval_dataset.py
────────────────────────
Pulls up to 100 products from product_vectors and generates a synthetic
eval dataset of (query, expected_products) pairs covering all intent types.

Usage:
    python -m evals.generate_eval_dataset

Output:
    evals/eval_dataset.json
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from openai import AsyncOpenAI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# ── Load env ──────────────────────────────────────────────────────────────────
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
DATABASE_URL   = os.getenv("NEON_DATABASE_URL") or os.getenv("DATABASE_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PRODUCT_LIMIT  = int(os.getenv("EVAL_PRODUCT_LIMIT", "100"))
ORG_ID         = os.getenv("EVAL_ORG_ID")           # None = all orgs
OUTPUT_PATH    = Path(__file__).parent / "eval_dataset.json"

if not DATABASE_URL:
    sys.exit("❌  DATABASE_URL not set in environment.")
if not OPENAI_API_KEY:
    sys.exit("❌  OPENAI_API_KEY not set in environment.")

_openai = AsyncOpenAI(api_key=OPENAI_API_KEY)

# ── Intent mix (how many queries per intent type) ─────────────────────────────
# Total = 100 queries across all intents
INTENT_MIX: dict[str, int] = {
    "exact_lookup":   10,
    "recommendation": 20,
    "comparison":     10,
    "price_filter":   15,
    "feature_search": 15,
    "browse":         10,
    "availability":    5,
    "off_topic":      15,   # these should be BLOCKED — test the intent gate
}

# ── Off-topic query bank (no product context needed) ─────────────────────────
OFF_TOPIC_QUERIES = [
    "hi there",
    "how are you?",
    "what is machine learning?",
    "tell me a joke",
    "who invented the internet?",
    "what is the capital of Bangladesh?",
    "explain blockchain to me",
    "write a poem about rain",
    "what time is it?",
    "thanks for your help",
    "kemon acho",
    "apni ke?",
    "what is ChatGPT?",
    "good morning",
    "bye bye",
]


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class EvalCase:
    query:              str
    intent:             str
    expected_products:  list[str]        # product names that should appear in answer
    expected_blocked:   bool             # True = intent gate should block this
    price_max:          Optional[float]
    budget_qualifier:   Optional[str]
    source_product_ids: list[str]        # product_ids used to generate this query
    notes:              str              # human-readable description of what's tested


# ── DB helpers ────────────────────────────────────────────────────────────────

async def fetch_products(session: AsyncSession) -> list[dict[str, Any]]:
    """Pull up to PRODUCT_LIMIT products from product_vectors."""
    where = "WHERE org_id = :org_id" if ORG_ID else ""
    params = {"org_id": ORG_ID, "limit": PRODUCT_LIMIT} if ORG_ID else {"limit": PRODUCT_LIMIT}

    sql = text(f"""
        SELECT
            org_id, product_id, name, category, brand,
            description, specifications, price, rating, review_count, status
        FROM product_vectors
        {where}
        ORDER BY RANDOM()
        LIMIT :limit
    """)

    result = await session.execute(sql, params)
    rows   = result.mappings().fetchall()

    products = []
    for r in rows:
        products.append({
            "org_id":          r["org_id"],
            "product_id":      r["product_id"],
            "name":            r["name"],
            "category":        r["category"] or "",
            "brand":           r["brand"] or "",
            "description":     (r["description"] or "")[:300],
            "specifications":  (r["specifications"] or "")[:200],
            "price":           float(r["price"]) if r["price"] else None,
            "rating":          float(r["rating"]) if r["rating"] else None,
            "review_count":    r["review_count"],
            "status":          r["status"] or "ACTIVE",
        })

    logger.info("Fetched %d products from DB", len(products))
    return products


# ── Query generator (LLM) ────────────────────────────────────────────────────

_GENERATOR_SYSTEM = """\
You are a test data generator for an e-commerce product search engine.

Given one or more product records, generate a realistic user search query
that matches the specified intent type.

Rules:
- The query must feel like something a real customer would type
- For price_filter: include a realistic price constraint based on the product price
- For exact_lookup: use the product name or brand + partial model
- For comparison: pick two products from the list
- For recommendation: describe a use case or need, not the product name directly
- For feature_search: ask about a specific feature the product has
- For browse: ask to see all products of a category
- For availability: ask if a specific product is in stock
- Vary language naturally — occasionally use Banglish (Bengali + English mix)
- Keep queries under 100 characters

Return ONLY a JSON object:
{
  "query": "<the search query>",
  "expected_products": ["<exact product name 1>", "<exact product name 2>"],
  "notes": "<one sentence: what this query tests>"
}

expected_products must be EXACT names from the input product list.
For off_topic: return empty expected_products list."""

async def generate_query_for_intent(
    intent: str,
    products: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Call gpt-4o-mini to generate one query for the given intent + products."""

    product_summaries = []
    for p in products:
        parts = [f"Name: {p['name']}"]
        if p["brand"]:       parts.append(f"Brand: {p['brand']}")
        if p["category"]:    parts.append(f"Category: {p['category']}")
        if p["price"]:       parts.append(f"Price: {p['price']:.0f}")
        if p["description"]: parts.append(f"Desc: {p['description'][:100]}")
        product_summaries.append(" | ".join(parts))

    user_prompt = (
        f"Intent type: {intent}\n\n"
        f"Products:\n" + "\n".join(f"- {s}" for s in product_summaries)
    )

    try:
        response = await _openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _GENERATOR_SYSTEM},
                {"role": "user",   "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.8,
            max_tokens=200,
            timeout=10.0,
        )
        raw  = response.choices[0].message.content.strip()
        data = json.loads(raw)
        return data
    except Exception as e:
        logger.warning("Query generation failed for intent=%s: %s", intent, e)
        return None


# ── Dataset builder ───────────────────────────────────────────────────────────

def _pick_products_for_intent(
    intent: str,
    all_products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Pick 1–3 relevant products to use as context for query generation."""
    if intent == "comparison":
        return random.sample(all_products, min(2, len(all_products)))
    if intent in ("exact_lookup", "availability"):
        return random.sample(all_products, 1)
    if intent == "browse":
        # Pick products from the same category if possible
        categories = list({p["category"] for p in all_products if p["category"]})
        if categories:
            cat = random.choice(categories)
            same_cat = [p for p in all_products if p["category"] == cat]
            return random.sample(same_cat, min(3, len(same_cat)))
    return random.sample(all_products, min(3, len(all_products)))


async def build_dataset(products: list[dict[str, Any]]) -> list[EvalCase]:
    cases: list[EvalCase] = []

    # ── Off-topic cases (no LLM needed) ──────────────────────────────────
    off_topic_pool = random.sample(
        OFF_TOPIC_QUERIES,
        min(INTENT_MIX["off_topic"], len(OFF_TOPIC_QUERIES)),
    )
    for q in off_topic_pool:
        cases.append(EvalCase(
            query              = q,
            intent             = "off_topic",
            expected_products  = [],
            expected_blocked   = True,
            price_max          = None,
            budget_qualifier   = None,
            source_product_ids = [],
            notes              = "Should be blocked by intent gate; answer should be off-topic message",
        ))
    logger.info("Generated %d off_topic cases", len(off_topic_pool))

    # ── Product-based intents (LLM-generated queries) ─────────────────────
    product_intents = {k: v for k, v in INTENT_MIX.items() if k != "off_topic"}

    tasks = []
    meta  = []   # parallel list tracking (intent, selected_products)

    for intent, count in product_intents.items():
        for _ in range(count):
            selected = _pick_products_for_intent(intent, products)
            tasks.append(generate_query_for_intent(intent, selected))
            meta.append((intent, selected))

    logger.info("Generating %d queries via LLM (this may take ~30-60s)...", len(tasks))

    # Run all LLM calls concurrently (batched to avoid rate limits)
    batch_size = 20
    results    = []
    for i in range(0, len(tasks), batch_size):
        batch   = tasks[i:i + batch_size]
        batch_r = await asyncio.gather(*batch, return_exceptions=True)
        results.extend(batch_r)
        if i + batch_size < len(tasks):
            await asyncio.sleep(1.0)   # brief pause between batches

    for (intent, selected), result in zip(meta, results):
        if isinstance(result, Exception) or result is None:
            logger.warning("Skipping failed generation for intent=%s", intent)
            continue

        query             = result.get("query", "").strip()
        expected_products = result.get("expected_products", [])
        notes             = result.get("notes", "")

        if not query:
            continue

        # Extract price constraint if present in expected products context
        price_max = None
        budget_qualifier = None
        if intent == "price_filter":
            prices = [p["price"] for p in selected if p.get("price")]
            if prices:
                price_max = max(prices) * 1.1   # give 10% headroom

        cases.append(EvalCase(
            query              = query,
            intent             = intent,
            expected_products  = expected_products,
            expected_blocked   = False,
            price_max          = price_max,
            budget_qualifier   = budget_qualifier,
            source_product_ids = [p["product_id"] for p in selected],
            notes              = notes,
        ))

    logger.info("Total eval cases built: %d", len(cases))
    return cases


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        connect_args={"ssl": "require"},
    )
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        products = await fetch_products(session)

    if not products:
        sys.exit("❌  No products found. Check your DATABASE_URL and EVAL_ORG_ID.")

    cases = await build_dataset(products)

    # Shuffle so intents are interleaved
    random.shuffle(cases)

    output = {
        "meta": {
            "total_cases":    len(cases),
            "intent_counts":  {},
            "product_count":  len(products),
            "org_id_filter":  ORG_ID,
        },
        "cases": [asdict(c) for c in cases],
    }

    # Count intents
    for c in cases:
        output["meta"]["intent_counts"][c.intent] = (
            output["meta"]["intent_counts"].get(c.intent, 0) + 1
        )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info("✅  Dataset saved → %s", OUTPUT_PATH)
    logger.info("Intent distribution: %s", output["meta"]["intent_counts"])


if __name__ == "__main__":
    asyncio.run(main())