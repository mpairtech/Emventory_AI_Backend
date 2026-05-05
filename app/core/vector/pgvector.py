from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError, OperationalError
from app.core.exceptions import VectorSearchError, DatabaseError
import logging
import math

logger = logging.getLogger(__name__)


# NOTE: _safe_float and _safe_int are duplicated from search.py.
# TODO: Move both to app/core/utils.py and import from there.

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
        # NaN/Inf check must happen on the float before casting —
        # int values can never be NaN or Inf.
        if math.isnan(f) or math.isinf(f):
            return None
        return int(f)
    except (TypeError, ValueError):
        return None


class VectorStore:

    @staticmethod
    def search(db, embedding, org_id=None, top_k: int = 10):
        """
        Search product_vectors by cosine similarity against the given embedding.

        Uses PostgreSQL + pgvector (<=> cosine distance operator).
        If org_id is provided, results are filtered to that organisation only.

        Args:
            db:        SQLAlchemy Session.
            embedding: List of floats (must match the indexed vector dimension).
            org_id:    Optional organisation filter.
            top_k:     Maximum number of results to return (default 10).
        """
        if not embedding:
            raise VectorSearchError("Embedding cannot be empty.")

        try:
            embedding_str = "[" + ",".join(map(str, embedding)) + "]"

            # FIX (Critical — SQL Injection): The original code used .format() to
            # splice where_clause into the SQL text:
            #
            #   where_clause = "WHERE org_id = :org_id" if org_id else ""
            #   sql = text("... {where_clause} ...".format(where_clause=where_clause))
            #
            # .format() and f-strings are equally dangerous here — both interpolate
            # strings directly into the SQL before SQLAlchemy ever sees the query.
            # This means the SQL structure is determined at runtime by a variable
            # derived from caller input, bypassing parameterisation entirely.
            #
            # Fix: one static SQL template with a NULL-safe conditional parameter.
            # `:org_id IS NULL OR org_id = :org_id` evaluates to TRUE for all rows
            # when org_id is None (passed as SQL NULL), filtering all orgs.
            # When org_id is set, it filters to that org only.
            # The SQL text is now a compile-time constant — no string construction,
            # no .format(), no f-strings, no branching SQL shape.
            sql = text("""
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
                WHERE (:org_id IS NULL OR org_id = :org_id)
                ORDER BY embedding <=> CAST(:q AS vector)
                LIMIT :top_k
            """)

            # org_id is passed directly as a bound parameter.
            # When None, SQLAlchemy sends NULL and the IS NULL branch fires,
            # returning rows across all orgs — identical to having no WHERE clause.
            rows = db.execute(
                sql,
                {"q": embedding_str, "org_id": org_id, "top_k": top_k},
            ).mappings().fetchall()

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
            raise DatabaseError(f"Database connection failed: {str(e)}")

        except SQLAlchemyError as e:
            logger.error("Database query error: %s", e, exc_info=True)
            raise VectorSearchError(f"Vector search query failed: {str(e)}")

        except (ValueError, TypeError) as e:
            logger.error("Data formatting error: %s", e, exc_info=True)
            raise VectorSearchError(f"Invalid data format: {str(e)}")

        except Exception as e:
            logger.error("Unexpected error in vector search: %s", e, exc_info=True)
            raise VectorSearchError(f"Vector search failed: {str(e)}")