from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError, IntegrityError, OperationalError
from app.db.models.vector import ProductVector
from app.core.exceptions import DatabaseError, ProductNotFoundError
import logging
 
logger = logging.getLogger(__name__)
 
 
class SearchRepository:
 
    @staticmethod
    async def upsert(db: AsyncSession, vector: ProductVector) -> None:
        try:
            stmt = select(ProductVector).where(
                ProductVector.org_id == vector.org_id,
                ProductVector.product_id == vector.product_id,
            )
            result = await db.execute(stmt)
            existing = result.scalar_one_or_none()
 
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
 
            await db.commit()
 
            if existing:
                await db.refresh(existing)
            else:
                await db.refresh(vector)
 
        except IntegrityError as e:
            await db.rollback()
            logger.error("Integrity constraint violation: %s", e)
            raise DatabaseError(f"Data integrity error: {e}")
 
        except OperationalError as e:
            await db.rollback()
            logger.error("Database operation failed: %s", e)
            raise DatabaseError(f"Database operation error: {e}")
 
        except SQLAlchemyError as e:
            await db.rollback()
            logger.error("Database error during upsert: %s", e)
            raise DatabaseError(f"Failed to save product: {e}")
 
        except Exception as e:
            await db.rollback()
            logger.error("Unexpected error during upsert: %s", e)
            raise DatabaseError(f"Unexpected database error: {e}")
 
    @staticmethod
    async def delete(db: AsyncSession, org_id: str, product_id: str) -> bool:
        try:
            stmt = select(ProductVector).where(
                ProductVector.org_id == org_id,
                ProductVector.product_id == product_id,
            )
            result = await db.execute(stmt)
            existing = result.scalar_one_or_none()
 
            if not existing:
                raise ProductNotFoundError(
                    f"Product '{product_id}' not found in org '{org_id}'"
                )
 
            await db.delete(existing)
            await db.commit()
            return True
 
        except ProductNotFoundError:
            raise
        except OperationalError as e:
            await db.rollback()
            logger.error("Database operation failed during delete: %s", e)
            raise DatabaseError(f"Database operation error: {e}")
        except SQLAlchemyError as e:
            await db.rollback()
            logger.error("Database error during delete: %s", e)
            raise DatabaseError(f"Failed to delete product: {e}")
        except Exception as e:
            await db.rollback()
            logger.error("Unexpected error during delete: %s", e)
            raise DatabaseError(f"Unexpected database error: {e}")
 
    @staticmethod
    async def get_by_id(
        db: AsyncSession, org_id: str, product_id: str
    ) -> ProductVector | None:
        try:
            stmt = select(ProductVector).where(
                ProductVector.org_id == org_id,
                ProductVector.product_id == product_id,
            )
            result = await db.execute(stmt)
            return result.scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error("Database error during get_by_id: %s", e)
            raise DatabaseError(f"Failed to fetch product: {e}")