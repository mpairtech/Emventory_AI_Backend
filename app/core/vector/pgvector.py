from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError, OperationalError
from app.core.exceptions import VectorSearchError, DatabaseError
import logging
import math

logger = logging.getLogger(__name__)


def _safe_float(v):
    if v is None:
        return None
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _safe_int(v):
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return int(f)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Shared SELECT columns
# ---------------------------------------------------------------------------

_SELECT_COLS = """
    SELECT org_id,
           product_id,
           name,
           category,
           brand,
           description,
           specifications,
           price,
           rating,
           review_count,
           status,
           1 - (embedding <=> CAST(:q AS vector)) AS score
    FROM product_vectors
"""

_ORDER_LIMIT = """
    ORDER BY embedding <=> CAST(:q AS vector)
    LIMIT :top_k
"""

# ---------------------------------------------------------------------------
# BM25 via PostgreSQL FTS — ts_rank_cd uses cover density (better for short
# product fields than plain ts_rank). We fetch top_k * 3 to give RRF enough
# candidates before fusion.
#
# Use websearch_to_tsquery instead of plainto_tsquery:
# - plainto_tsquery: ALL tokens must match (AND) → "suggest me wireless earbuds"
#   fails because "suggest" and "me" are not in product vectors
# - websearch_to_tsquery: handles natural language, treats unknown words more
#   loosely, and Postgres strips English stop words automatically
# ---------------------------------------------------------------------------

_BM25_SELECT = """
    SELECT org_id,
           product_id,
           name,
           category,
           brand,
           description,
           specifications,
           price,
           rating,
           review_count,
           status,
           ts_rank_cd(search_vector, websearch_to_tsquery('english', :query), 32) AS bm25_score
    FROM product_vectors
"""

_BM25_ORDER_LIMIT = """
    ORDER BY bm25_score DESC
    LIMIT :top_k
"""


# Intent/filler words that appear in search queries but never in product data.
# Stripping these before FTS prevents plainto/websearch_to_tsquery from
# requiring them as match tokens (AND semantics).
_INTENT_WORDS = frozenset({
    "suggest", "me", "give", "show", "find", "get", "want", "need",
    "looking", "search", "recommend", "recommendation", "help", "please",
    "can", "you", "i", "a", "an", "the", "for", "to", "of", "in", "on",
    "at", "with", "some", "any", "good", "best", "nice", "great", "top",
    "my", "our", "your", "is", "are", "was", "be", "do", "does", "did",
    "what", "which", "where", "when", "how", "that", "this", "those",
    "these", "it", "its", "and", "or", "but", "not", "no", "yes",
})


def _clean_for_bm25(query: str) -> str:
    """
    Strip intent/filler words that exist in search queries but not in
    product descriptions. Keeps only content-bearing tokens for FTS.
    Falls back to original query if stripping leaves nothing.
    """
    tokens = query.strip().split()
    content_tokens = [t for t in tokens if t.lower() not in _INTENT_WORDS]
    cleaned = " ".join(content_tokens)
    return cleaned if cleaned.strip() else query


def _row_to_dict(row, score_key: str = "score") -> dict:
    return {
        "org_id":           row["org_id"],
        "product_id":       row["product_id"],
        "name":             row["name"],
        "category":         row["category"],
        "brand":            row["brand"],
        "description":      row["description"],
        "specifications":   row["specifications"],
        "price":            _safe_float(row["price"]),
        "rating":           _safe_float(row["rating"]),
        "review_count":     _safe_int(row["review_count"]),
        "status":           row["status"],
        "similarity_score": _safe_float(row[score_key]) or 0.0,
    }


class VectorStore:

    # ============================================================
    # VECTOR SEARCH  (unchanged)
    # ============================================================

    @staticmethod
    async def search(
        db: AsyncSession,
        embedding: list[float],
        org_id: str | None = None,
        top_k: int = 10,
    ) -> list[dict]:
        """
        Cosine-similarity search against product_vectors using pgvector.
        Branch in Python to avoid asyncpg AmbiguousParameterError.
        """
        if not embedding:
            raise VectorSearchError("Embedding cannot be empty.")

        try:
            embedding_str = "[" + ",".join(map(str, embedding)) + "]"
            params = {"q": embedding_str, "top_k": top_k}

            if org_id is None:
                sql = text(_SELECT_COLS + _ORDER_LIMIT)
            else:
                sql = text(_SELECT_COLS + "WHERE org_id = :org_id\n" + _ORDER_LIMIT)
                params["org_id"] = org_id

            result = await db.execute(sql, params)
            rows = result.mappings().fetchall()
            return [_row_to_dict(r) for r in rows]

        except OperationalError as e:
            logger.error("Database connection error: %s", e, exc_info=True)
            raise DatabaseError(f"Database connection failed: {e}")
        except SQLAlchemyError as e:
            logger.error("Database query error: %s", e, exc_info=True)
            raise VectorSearchError(f"Vector search query failed: {e}")
        except (ValueError, TypeError) as e:
            logger.error("Data formatting error: %s", e, exc_info=True)
            raise VectorSearchError(f"Invalid data format: {e}")
        except Exception as e:
            logger.error("Unexpected error in vector search: %s", e, exc_info=True)
            raise VectorSearchError(f"Vector search failed: {e}")

    # ============================================================
    # BM25 SEARCH  (PostgreSQL FTS via tsvector/ts_rank_cd)
    # ============================================================

    @staticmethod
    async def bm25_search(
        db: AsyncSession,
        query: str,
        org_id: str | None = None,
        top_k: int = 10,
    ) -> list[dict]:
        """
        Full-text search using PostgreSQL tsvector + ts_rank_cd.
        Requires the search_vector generated column + GIN index from migration.
        Returns results with bm25_score in similarity_score field.
        """
        if not query or not query.strip():
            return []

        try:
            # Fetch more candidates than top_k — RRF needs a wider pool
            fetch_k = min(top_k * 3, 50)
            cleaned_query = _clean_for_bm25(query)
            logger.debug("BM25 cleaned query: '%s' → '%s'", query, cleaned_query)
            params = {"query": cleaned_query, "top_k": fetch_k}

            if org_id is None:
                sql = text(
                    _BM25_SELECT
                    + "WHERE search_vector @@ websearch_to_tsquery('english', :query)\n"
                    + _BM25_ORDER_LIMIT
                )
            else:
                sql = text(
                    _BM25_SELECT
                    + "WHERE org_id = :org_id\n"
                    + "  AND search_vector @@ websearch_to_tsquery('english', :query)\n"
                    + _BM25_ORDER_LIMIT
                )
                params["org_id"] = org_id

            result = await db.execute(sql, params)
            rows = result.mappings().fetchall()

            return [_row_to_dict(r, score_key="bm25_score") for r in rows]

        except OperationalError as e:
            logger.error("BM25 DB connection error: %s", e, exc_info=True)
            raise DatabaseError(f"Database connection failed: {e}")
        except SQLAlchemyError as e:
            logger.error("BM25 query error: %s", e, exc_info=True)
            raise VectorSearchError(f"BM25 search query failed: {e}")
        except Exception as e:
            logger.error("Unexpected BM25 error: %s", e, exc_info=True)
            raise VectorSearchError(f"BM25 search failed: {e}")

    # ============================================================
    # HYBRID SEARCH  (vector + BM25 fused via RRF)
    # ============================================================

    @staticmethod
    async def hybrid_search(
        db: AsyncSession,
        embedding: list[float],
        query: str,
        org_id: str | None = None,
        top_k: int = 10,
        vector_weight: float = 0.5,
        bm25_weight: float = 0.5,
        rrf_k: int = 60,
    ) -> list[dict]:
        """
        Hybrid search: vector cosine similarity + BM25 (PostgreSQL FTS),
        fused using Reciprocal Rank Fusion (RRF).

        RRF formula:
            rrf_score(d) = vector_weight * 1/(k + rank_v)
                         + bm25_weight  * 1/(k + rank_b)

        Both searches run concurrently via asyncio.gather.
        Falls back gracefully if BM25 returns nothing (e.g. before migration).
        """
        if not embedding:
            raise VectorSearchError("Embedding cannot be empty.")

        # Run sequentially — asyncio.gather on the same SQLAlchemy AsyncSession
        # raises InvalidRequestError ("concurrent operations not permitted").
        # Sequential is safe and still fast — both queries hit the same DB connection.
        try:
            vector_results = await VectorStore.search(db, embedding, org_id=org_id, top_k=top_k * 2)
        except Exception as e:
            logger.error("Vector search failed in hybrid: %s", e)
            vector_results = []

        try:
            bm25_results = await VectorStore.bm25_search(db, query, org_id=org_id, top_k=top_k * 2)
        except Exception as e:
            logger.warning("BM25 search failed in hybrid (falling back to vector only): %s", e)
            bm25_results = []

        # Handle partial failures gracefully
        if isinstance(vector_results, Exception):
            logger.error("Vector search failed in hybrid: %s", vector_results)
            vector_results = []
        if isinstance(bm25_results, Exception):
            logger.warning("BM25 search failed in hybrid (falling back to vector only): %s", bm25_results)
            bm25_results = []

        # If BM25 returned nothing, return vector results directly
        if not bm25_results:
            logger.info("BM25 returned no results — using vector only")
            return vector_results[:top_k]

        # If vector returned nothing, return BM25 results directly
        if not vector_results:
            logger.info("Vector returned no results — using BM25 only")
            return bm25_results[:top_k]

        # --- RRF Fusion ---
        # Build rank maps: product_id → rank (1-indexed)
        vector_rank: dict[str, int] = {
            r["product_id"]: idx + 1
            for idx, r in enumerate(vector_results)
        }
        bm25_rank: dict[str, int] = {
            r["product_id"]: idx + 1
            for idx, r in enumerate(bm25_results)
        }

        # Merge all unique products, keyed by product_id
        all_products: dict[str, dict] = {}
        for r in vector_results:
            all_products[r["product_id"]] = r
        for r in bm25_results:
            if r["product_id"] not in all_products:
                all_products[r["product_id"]] = r

        # Compute RRF score for each product
        rrf_scores: dict[str, float] = {}
        max_vector_rank = len(vector_results)
        max_bm25_rank = len(bm25_results)

        for pid in all_products:
            v_rank = vector_rank.get(pid, max_vector_rank + rrf_k)
            b_rank = bm25_rank.get(pid, max_bm25_rank + rrf_k)
            rrf_scores[pid] = (
                vector_weight * (1.0 / (rrf_k + v_rank))
                + bm25_weight * (1.0 / (rrf_k + b_rank))
            )

        # Sort by RRF score, attach as similarity_score
        sorted_pids = sorted(rrf_scores, key=lambda p: rrf_scores[p], reverse=True)

        fused = []
        for pid in sorted_pids[:top_k]:
            product = dict(all_products[pid])
            product["similarity_score"] = round(rrf_scores[pid], 6)
            fused.append(product)

        logger.info(
            "Hybrid search | org=%s | vector=%d | bm25=%d | fused=%d | weights=(%.1f,%.1f)",
            org_id, len(vector_results), len(bm25_results), len(fused),
            vector_weight, bm25_weight,
        )

        return fused