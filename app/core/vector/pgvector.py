from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError, OperationalError
from app.core.exceptions import VectorSearchError, DatabaseError
import logging

logger = logging.getLogger(__name__)

class VectorStore:
    
    @staticmethod
    def search(db, embedding):
        try:
            if not embedding or len(embedding) == 0:
                raise VectorSearchError("Embedding cannot be empty")
            
            embedding_str = '[' + ','.join(map(str, embedding)) + ']'
            
            sql = text("""
                SELECT product_id,
                       name,
                       category,
                       price,
                       1 - (embedding <=> CAST(:q AS vector)) AS score
                FROM product_vectors
                ORDER BY embedding <=> CAST(:q AS vector)
                LIMIT 10
            """)
            
            results = db.execute(sql, {"q": embedding_str}).fetchall()
            
            return [
                {
                    "product_id": row[0],
                    "name": row[1],
                    "category": row[2],
                    "price": float(row[3]),
                    "similarity_score": float(row[4])
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