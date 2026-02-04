from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError, IntegrityError, OperationalError
from app.db.models.vector import ProductVector
from app.core.exceptions import DatabaseError, ProductNotFoundError
import logging

logger = logging.getLogger(__name__)

class SearchRepository:
    
    @staticmethod
    def upsert(db: Session, vector: ProductVector):
        try:
            existing = db.query(ProductVector).filter(
                ProductVector.org_id == vector.org_id,
                ProductVector.product_id == vector.product_id,
            ).first()
            
            if existing:
                existing.embedding = vector.embedding
                existing.name = vector.name
                existing.category = vector.category
                existing.brand = vector.brand
                existing.description = vector.description
                existing.specifications = vector.specifications
                existing.price = vector.price
                existing.rating = vector.rating
                existing.review_count = vector.review_count
                existing.status = vector.status
            else:
                db.add(vector)
            
            db.commit()
            
            if existing:
                db.refresh(existing)
            else:
                db.refresh(vector)
                
        except IntegrityError as e:
            db.rollback()
            logger.error(f"Integrity constraint violation: {e}")
            raise DatabaseError(f"Data integrity error: {str(e)}")
            
        except OperationalError as e:
            db.rollback()
            logger.error(f"Database operation failed: {e}")
            raise DatabaseError(f"Database operation error: {str(e)}")
            
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error during upsert: {e}")
            raise DatabaseError(f"Failed to save product: {str(e)}")
            
        except Exception as e:
            db.rollback()
            logger.error(f"Unexpected error during upsert: {e}")
            raise DatabaseError(f"Unexpected database error: {str(e)}")