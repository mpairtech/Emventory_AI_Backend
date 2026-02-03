from sqlalchemy import Column, Text, Float, String, UniqueConstraint
from pgvector.sqlalchemy import Vector
from sqlalchemy.orm import declarative_base

from app.core.config import EMBEDDING_DIM

Base = declarative_base()


class ProductVector(Base):
    """Vector store for AI search. org_id + product_id = one row per product per org (matches MySQL emventory_admin_db.product)."""
    __tablename__ = "product_vectors"
    __table_args__ = (
        UniqueConstraint("org_id", "product_id", name="uq_product_vectors_org_product"),
    )

    # Identity
    org_id = Column(String(255), primary_key=True, nullable=False, index=True)
    product_id = Column(String(50), primary_key=True, nullable=False)

    # AI Vector
    embedding = Column(Vector(EMBEDDING_DIM), nullable=False)

    # Core searchable fields
    name = Column(Text, nullable=False)              # Product name
    category = Column(Text, nullable=True)           # Category name/path
    brand = Column(Text, nullable=True)              # Brand / manufacturer

    # Rich text for semantic quality
    description = Column(Text, nullable=True)        # Full description
    specifications = Column(Text, nullable=True)     # JSON or text specs

    # Commerce fields
    price = Column(Float, nullable=True)             # Current price
    rating = Column(Float, nullable=True)            # Avg rating from review table
    review_count = Column(Float, nullable=True)      # Number of reviews

    status = Column(String(50), nullable=True)       # ACTIVE / INACTIVE / DRAFT
