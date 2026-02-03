from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError, OperationalError
from app.core.exceptions import VectorSearchError, DatabaseError
import logging

logger = logging.getLogger(__name__)

class VectorStore:
    
    @staticmethod
    def search(db, embedding, org_id=None):
        """Search by embedding. If org_id is set, only products for that org are returned (MySQL org-based)."""
        try:
            if not embedding or len(embedding) == 0:
                raise VectorSearchError("Embedding cannot be empty")
            
            embedding_str = '[' + ','.join(map(str, embedding)) + ']'
            params = {"q": embedding_str}
            
            where_clause = "WHERE org_id = :org_id" if org_id else ""
            if org_id:
                params["org_id"] = org_id
            
            sql = text(f"""
                SELECT org_id, product_id,
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
                {where_clause}
                ORDER BY embedding <=> CAST(:q AS vector)
                LIMIT 10
            """)
            
            results = db.execute(sql, params).fetchall()
            
            return [
                {
                    "org_id": row[0],
                    "product_id": row[1],
                    "name": row[2],
                    "category": row[3],
                    "brand": row[4],
                    "description": row[5],
                    "specifications": row[6],
                    "price": float(row[7]) if row[7] else None,
                    "rating": float(row[8]) if row[8] else None,
                    "review_count": int(row[9]) if row[9] else None,
                    "status": row[10],
                    "similarity_score": float(row[11])
                }
                for row in results
            ]
            
        except OperationalError as e:
            logger.error(f"Database connection error: {e}")
            raise DatabaseError(f"Database connection failed: {str(e)}")
            
        except SQLAlchemyError as e:
            logger.error(f"Database query error: {e}")
            raise VectorSearchError(f"Vector search query failed: {str(e)}")
            
        except (ValueError, TypeError) as e:
            logger.error(f"Data formatting error: {e}")
            raise VectorSearchError(f"Invalid data format: {str(e)}")
            
        except Exception as e:
            logger.error(f"Unexpected error in vector search: {e}")
            raise VectorSearchError(f"Vector search failed: {str(e)}")