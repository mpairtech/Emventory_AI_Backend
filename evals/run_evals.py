"""
run_evals.py
────────────
Runs every case in eval_dataset.json through the RAG pipeline and
writes a detailed CSV report + a summary JSON.

Usage:
    python -m evals.run_evals [--dataset evals/eval_dataset.json]
                              [--output  evals/eval_report.csv]
                              [--provider openai|gemini]
                              [--concurrency 5]

Metrics per case:
    products_found       — fraction of expected products found in answer
    hallucination        — True if answer contains names not in sources
    relevance_score      — LLM judge 0–1: right products recommended?
    faithfulness_score   — LLM judge 0–1: answer grounded in context?
    order_correct        — True if top expected product is listed first
    off_topic_leaked     — True if blocked query got a product answer
    budget_respected     — True if no over-budget product in sources
    latency_ms           — end-to-end response time
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()

# ── project root on sys.path so app.* imports work ───────────────────────────
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.modules.search.service import SearchService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
DATABASE_URL   = os.getenv("NEON_DATABASE_URL") or os.getenv("DATABASE_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not DATABASE_URL:
    sys.exit("❌  DATABASE_URL not set.")
if not OPENAI_API_KEY:
    sys.exit("❌  OPENAI_API_KEY not set.")

_judge_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class EvalResult:
    # Identity
    case_index:           int
    intent:               str
    query:                str
    notes:                str

    # Raw pipeline output
    answer:               str      = ""
    source_names:         str      = ""   # comma-separated product names from sources
    off_topic_flag:       bool     = False
    latency_ms:           float    = 0.0

    # Exact-match metrics
    products_found:       float    = 0.0   # 0.0–1.0 fraction of expected found
    hallucination:        bool     = False
    order_correct:        bool     = False
    off_topic_leaked:     bool     = False
    budget_respected:     bool     = True

    # LLM-judge metrics
    relevance_score:      float    = 0.0   # 0.0–1.0
    faithfulness_score:   float    = 0.0   # 0.0–1.0
    judge_reasoning:      str      = ""

    # Error
    error:                str      = ""


# ── Exact-match scorers ───────────────────────────────────────────────────────

def _normalize(name: str) -> str:
    """Lowercase + collapse whitespace for fuzzy name matching."""
    return re.sub(r"\s+", " ", name.lower().strip())


def score_products_found(
    expected: list[str],
    answer: str,
) -> float:
    """Fraction of expected product names found in the answer text."""
    if not expected:
        return 1.0   # nothing expected → trivially satisfied

    answer_norm = _normalize(answer)
    found = sum(
        1 for name in expected
        if _normalize(name) in answer_norm
    )
    return round(found / len(expected), 3)


def score_hallucination(
    answer: str,
    source_names: list[str],
) -> bool:
    """
    True if the answer contains a product-like name NOT in the sources.
    Heuristic: look for bullet lines (• Name) and check against sources.
    """
    if not answer or not source_names:
        return False

    source_norms = {_normalize(n) for n in source_names}

    # Extract bulleted lines from the answer
    bullet_lines = re.findall(r"[•\-\*]\s*(.+)", answer)
    if not bullet_lines:
        return False

    for line in bullet_lines:
        line_norm = _normalize(line.strip())
        # Check if this bullet matches any source
        if not any(
            src in line_norm or line_norm in src
            for src in source_norms
        ):
            logger.debug("Potential hallucination: %r not in sources", line)
            return True

    return False


def score_order_correct(
    expected: list[str],
    answer: str,
) -> bool:
    """True if the first expected product appears before others in the answer."""
    if not expected or len(expected) < 2:
        return True   # nothing to order

    positions = {}
    answer_norm = _normalize(answer)
    for name in expected:
        idx = answer_norm.find(_normalize(name))
        if idx != -1:
            positions[name] = idx

    if not positions:
        return False

    first_found = min(positions, key=positions.get)
    return first_found == expected[0]


def score_off_topic_leaked(
    expected_blocked: bool,
    off_topic_flag: bool,
    source_names: list[str],
) -> bool:
    """
    True if the query was supposed to be blocked but sources were returned
    (meaning a product answer was given instead of the off-topic message).
    """
    if not expected_blocked:
        return False
    return bool(source_names)   # sources present = pipeline answered with products


def score_budget_respected(
    price_max: Optional[float],
    source_names_with_prices: list[dict],
) -> bool:
    """True if no source product exceeds the price ceiling."""
    if price_max is None:
        return True
    for product in source_names_with_prices:
        price = product.get("price")
        if price is not None and float(price) > price_max * 1.05:   # 5% tolerance
            return False
    return True


# ── LLM Judge ─────────────────────────────────────────────────────────────────

_JUDGE_SYSTEM = """\
You are an expert evaluator for an e-commerce product search RAG system.

You will be given:
1. A user query
2. The retrieved source products (ground truth context)
3. The system's answer

Score the answer on two dimensions:

RELEVANCE (0.0–1.0):
- 1.0 = Answer recommends exactly the right products for the query
- 0.7 = Mostly right, minor misses
- 0.4 = Partially relevant, some wrong products included
- 0.1 = Wrong products recommended
- 0.0 = Completely irrelevant or empty

FAITHFULNESS (0.0–1.0):
- 1.0 = Every claim in the answer is supported by the source products
- 0.7 = Mostly faithful, minor unsupported details
- 0.4 = Some claims not supported by sources
- 0.0 = Answer invents product names or details not in sources

Return ONLY a JSON object:
{
  "relevance_score": <float 0.0-1.0>,
  "faithfulness_score": <float 0.0-1.0>,
  "reasoning": "<one sentence explaining your scores>"
}"""


async def llm_judge(
    query: str,
    sources: list[dict],
    answer: str,
) -> tuple[float, float, str]:
    """Returns (relevance_score, faithfulness_score, reasoning)."""

    if not answer or not answer.strip():
        return 0.0, 0.0, "Empty answer"

    source_text = "\n".join(
        f"- {s.get('name', 'Unknown')} "
        f"(price: {s.get('price', 'N/A')}, "
        f"brand: {s.get('brand', 'N/A')}, "
        f"category: {s.get('category', 'N/A')})"
        for s in sources[:10]
    )

    user_prompt = (
        f"Query: {query}\n\n"
        f"Source products:\n{source_text or '(none)'}\n\n"
        f"System answer:\n{answer}"
    )

    try:
        response = await _judge_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _JUDGE_SYSTEM},
                {"role": "user",   "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=150,
            timeout=10.0,
        )
        raw  = response.choices[0].message.content.strip()
        data = json.loads(raw)

        relevance    = float(data.get("relevance_score",    0.0))
        faithfulness = float(data.get("faithfulness_score", 0.0))
        reasoning    = str(data.get("reasoning", ""))

        return round(relevance, 3), round(faithfulness, 3), reasoning

    except Exception as e:
        logger.warning("Judge call failed for query=%r: %s", query, e)
        return 0.0, 0.0, f"Judge error: {e}"


# ── Single case runner ────────────────────────────────────────────────────────

async def run_single_case(
    index: int,
    case: dict,
    session: AsyncSession,
    provider: str,
) -> EvalResult:

    result = EvalResult(
        case_index = index,
        intent     = case["intent"],
        query      = case["query"],
        notes      = case.get("notes", ""),
    )

    t0 = time.monotonic()
    try:
        rag_response = await SearchService.rag_search(
            db           = session,
            query        = case["query"],
            org_id       = None,   # eval across all orgs
            llm_provider = provider,
            top_k        = 5,
            language     = "en",
        )
        result.latency_ms = round((time.monotonic() - t0) * 1000, 1)

        answer       = rag_response.get("answer", "")
        sources      = rag_response.get("sources", [])
        off_topic    = rag_response.get("off_topic", False)

        result.answer        = answer
        result.off_topic_flag = off_topic
        result.source_names  = ", ".join(s.get("name", "") for s in sources)

        source_name_list = [s.get("name", "") for s in sources]
        expected         = case.get("expected_products", [])
        expected_blocked = case.get("expected_blocked", False)
        price_max        = case.get("price_max")

        # ── Exact-match metrics ───────────────────────────────────────────
        result.products_found   = score_products_found(expected, answer)
        result.hallucination    = score_hallucination(answer, source_name_list)
        result.order_correct    = score_order_correct(expected, answer)
        result.off_topic_leaked = score_off_topic_leaked(
            expected_blocked, off_topic, source_name_list
        )
        result.budget_respected = score_budget_respected(price_max, sources)

        # ── LLM judge ─────────────────────────────────────────────────────
        (
            result.relevance_score,
            result.faithfulness_score,
            result.judge_reasoning,
        ) = await llm_judge(case["query"], sources, answer)

    except Exception as e:
        result.latency_ms  = round((time.monotonic() - t0) * 1000, 1)
        result.error       = str(e)
        logger.error("Case %d failed: %s | query=%r", index, e, case["query"])

    return result


# ── CSV writer ────────────────────────────────────────────────────────────────

CSV_FIELDS = [
    "case_index", "intent", "query", "notes",
    "latency_ms",
    "products_found", "hallucination", "order_correct",
    "off_topic_leaked", "budget_respected",
    "relevance_score", "faithfulness_score",
    "off_topic_flag", "answer", "source_names",
    "judge_reasoning", "error",
]


def write_csv(results: list[EvalResult], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for r in results:
            row = asdict(r)
            # Truncate long answer for readability
            row["answer"] = (row["answer"] or "")[:300]
            writer.writerow({k: row[k] for k in CSV_FIELDS})
    logger.info("CSV written → %s", output_path)


# ── Summary builder ───────────────────────────────────────────────────────────

def build_summary(results: list[EvalResult]) -> dict:
    if not results:
        return {}

    total     = len(results)
    succeeded = [r for r in results if not r.error]
    n         = len(succeeded) or 1

    def avg(vals):
        return round(sum(vals) / len(vals), 3) if vals else 0.0

    # Per-intent breakdown
    intent_groups: dict[str, list[EvalResult]] = {}
    for r in succeeded:
        intent_groups.setdefault(r.intent, []).append(r)

    intent_summary = {}
    for intent, group in intent_groups.items():
        ng = len(group) or 1
        intent_summary[intent] = {
            "count":             len(group),
            "avg_relevance":     avg([r.relevance_score    for r in group]),
            "avg_faithfulness":  avg([r.faithfulness_score for r in group]),
            "avg_products_found":avg([r.products_found     for r in group]),
            "hallucination_rate":round(sum(r.hallucination for r in group) / ng, 3),
            "avg_latency_ms":    avg([r.latency_ms         for r in group]),
        }

    return {
        "total_cases":          total,
        "succeeded":            len(succeeded),
        "failed":               total - len(succeeded),
        "avg_relevance":        avg([r.relevance_score    for r in succeeded]),
        "avg_faithfulness":     avg([r.faithfulness_score for r in succeeded]),
        "avg_products_found":   avg([r.products_found     for r in succeeded]),
        "hallucination_rate":   round(sum(r.hallucination     for r in succeeded) / n, 3),
        "off_topic_leak_rate":  round(sum(r.off_topic_leaked  for r in succeeded) / n, 3),
        "budget_respected_rate":round(sum(r.budget_respected  for r in succeeded) / n, 3),
        "order_correct_rate":   round(sum(r.order_correct     for r in succeeded) / n, 3),
        "avg_latency_ms":       avg([r.latency_ms             for r in succeeded]),
        "by_intent":            intent_summary,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(args: argparse.Namespace) -> None:
    dataset_path = Path(args.dataset)
    output_path  = Path(args.output)
    provider     = args.provider
    concurrency  = args.concurrency

    if not dataset_path.exists():
        sys.exit(f"❌  Dataset not found: {dataset_path}\n"
                 "    Run generate_eval_dataset.py first.")

    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    cases   = dataset["cases"]
    logger.info("Loaded %d eval cases from %s", len(cases), dataset_path)

    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        connect_args={"ssl": "require"},
    )
    AsyncSessionLocal = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    results: list[EvalResult] = []
    semaphore = asyncio.Semaphore(concurrency)

    async def run_with_semaphore(index: int, case: dict) -> EvalResult:
        async with semaphore:
            async with AsyncSessionLocal() as session:
                result = await run_single_case(index, case, session, provider)
                logger.info(
                    "Case %3d/%d | intent=%-15s | relevance=%.2f | "
                    "faithful=%.2f | latency=%5.0fms | %s",
                    index + 1, len(cases),
                    result.intent,
                    result.relevance_score,
                    result.faithfulness_score,
                    result.latency_ms,
                    f"ERROR: {result.error[:60]}" if result.error else "OK",
                )
                return result

    tasks   = [run_with_semaphore(i, c) for i, c in enumerate(cases)]
    results = await asyncio.gather(*tasks)

    # ── Write CSV ──────────────────────────────────────────────────────────
    write_csv(list(results), output_path)

    # ── Write summary JSON ─────────────────────────────────────────────────
    summary      = build_summary(list(results))
    summary_path = output_path.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))

    # ── Print summary to console ───────────────────────────────────────────
    print("\n" + "═" * 60)
    print("  EVAL SUMMARY")
    print("═" * 60)
    print(f"  Total cases       : {summary['total_cases']}")
    print(f"  Succeeded         : {summary['succeeded']}")
    print(f"  Failed            : {summary['failed']}")
    print("─" * 60)
    print(f"  Avg relevance     : {summary['avg_relevance']:.3f}")
    print(f"  Avg faithfulness  : {summary['avg_faithfulness']:.3f}")
    print(f"  Avg products found: {summary['avg_products_found']:.3f}")
    print(f"  Hallucination rate: {summary['hallucination_rate']:.3f}")
    print(f"  Off-topic leak    : {summary['off_topic_leak_rate']:.3f}")
    print(f"  Budget respected  : {summary['budget_respected_rate']:.3f}")
    print(f"  Order correct     : {summary['order_correct_rate']:.3f}")
    print(f"  Avg latency       : {summary['avg_latency_ms']:.0f}ms")
    print("─" * 60)
    print("  By intent:")
    for intent, data in summary.get("by_intent", {}).items():
        print(
            f"    {intent:<18} n={data['count']:2d} | "
            f"rel={data['avg_relevance']:.2f} | "
            f"faith={data['avg_faithfulness']:.2f} | "
            f"halluc={data['hallucination_rate']:.2f}"
        )
    print("═" * 60)
    print(f"\n  CSV    → {output_path}")
    print(f"  Summary→ {summary_path}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run RAG evals")
    parser.add_argument(
        "--dataset",
        default="evals/eval_dataset.json",
        help="Path to eval_dataset.json",
    )
    parser.add_argument(
        "--output",
        default="evals/eval_report.csv",
        help="Path for output CSV",
    )
    parser.add_argument(
        "--provider",
        default="openai",
        choices=["openai", "gemini"],
        help="LLM provider for RAG generation",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Max parallel cases (default: 5)",
    )
    args = parser.parse_args()
    asyncio.run(main(args))