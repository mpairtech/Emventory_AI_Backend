from sqlalchemy import Column, BigInteger, Text, Float
from pgvector.sqlalchemy import Vector
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class ProductVector(Base):
    __tablename__ = "product_vectors"

    product_id = Column(BigInteger, primary_key=True)
    embedding = Column(Vector(768))
    name = Column(Text)
    category = Column(Text)
    price = Column(Float)
