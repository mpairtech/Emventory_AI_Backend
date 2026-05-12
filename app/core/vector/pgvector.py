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


# Shared SELECT columns — avoids repeating them in both query branches
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


class VectorStore:

    @staticmethod
    async def search(
        db: AsyncSession,
        embedding: list[float],
        org_id: str | None = None,
        top_k: int = 10,
    ) -> list[dict]:
        """
        Async cosine-similarity search against product_vectors using pgvector.

        asyncpg uses PostgreSQL's binary protocol and prepares statements
        server-side, so every parameter must be unambiguously typed at
        prepare time.  The conditional  ($2 IS NULL OR col = $2)  pattern
        gives PostgreSQL no type hint for $2, causing AmbiguousParameterError.

        Fix: branch in Python so each query branch has no nullable params.
        """
        if not embedding:
            raise VectorSearchError("Embedding cannot be empty.")

        try:
            embedding_str = "[" + ",".join(map(str, embedding)) + "]"
            params = {"q": embedding_str, "top_k": top_k}

            if org_id is None:
                # No org filter — no ambiguous parameter at all
                sql = text(_SELECT_COLS + _ORDER_LIMIT)
            else:
                # org_id is a concrete value; PostgreSQL infers type from the column
                sql = text(_SELECT_COLS + "WHERE org_id = :org_id\n" + _ORDER_LIMIT)
                params["org_id"] = org_id

            result = await db.execute(sql, params)
            rows = result.mappings().fetchall()

            return [
                {
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
                    "similarity_score": _safe_float(row["score"]) or 0.0,
                }
                for row in rows
            ]

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