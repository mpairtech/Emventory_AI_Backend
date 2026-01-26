from pydantic import BaseModel, Field, field_validator
from typing import Optional

class ProductIndexRequest(BaseModel):
    product_id: int = Field(..., gt=0, description="Product ID must be positive")
    name: str = Field(..., min_length=1, max_length=100, description="Product name")
    category: str = Field(..., min_length=1, max_length=100, description="Product category")
    price: float = Field(..., gt=0, description="Price must be positive")
    
    @field_validator('name', 'category')
    @classmethod
    def validate_not_empty(cls, v: str) -> str:
        if not v or v.strip() == "":
            raise ValueError("Field cannot be empty or whitespace")
        return v.strip()

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=100, description="Search query")
    
    @field_validator('query')
    @classmethod
    def validate_query(cls, v: str) -> str:
        if not v or v.strip() == "":
            raise ValueError("Query cannot be empty or whitespace")
        return v.strip()

class ProductResponse(BaseModel):
    product_id: int
    name: str
    category: str
    price: float
    similarity_score: float

class RAGResponse(BaseModel):
    answer: str
    sources: list[ProductResponse]

class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None