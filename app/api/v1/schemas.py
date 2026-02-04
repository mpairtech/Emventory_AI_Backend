from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional

# Max text length for embedding to avoid token limit / cost (Gemini)
EMBEDDING_TEXT_MAX_LENGTH = 8192
QUERY_MAX_LENGTH = 500


class ProductIndexRequest(BaseModel):
    """Only these fields are accepted. Extra fields in request body are rejected (422)."""
    model_config = ConfigDict(extra="forbid")

    org_id: str = Field(..., min_length=1, max_length=255, description="Org ID (MySQL organization.org_id)")
    product_id: str = Field(..., min_length=1, max_length=50, description="Product ID (MySQL product.product_id)")
    name: str = Field(..., min_length=1, max_length=255, description="Product name")
    
    # Optional fields for better search
    category: Optional[str] = Field(None, max_length=255, description="Product category")
    brand: Optional[str] = Field(None, max_length=255, description="Product brand/manufacturer")
    description: Optional[str] = Field(None, max_length=5000, description="Product description/details")
    specifications: Optional[str] = Field(None, max_length=2000, description="Technical specifications/details")
    price: Optional[float] = Field(None, gt=0, description="Price must be positive if provided")
    rating: Optional[float] = Field(None, ge=0, le=5, description="Average rating (0-5 stars)")
    review_count: Optional[int] = Field(None, ge=0, description="Number of reviews")
    status: Optional[str] = Field(None, max_length=50, description="Product status (e.g., ACTIVE, INACTIVE, DRAFT)")
    
    @field_validator('name', mode="after")
    @classmethod
    def validate_not_empty(cls, v: str) -> str:
        if not v or v.strip() == "":
            raise ValueError("Field can't be empty")
        return v.strip()
    
    @field_validator('category', 'brand', 'description', 'status', 'specifications', mode="after")
    @classmethod
    def strip_optional_fields(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        s = v.strip()
        return s if s else None

class ListIndexedRequest(BaseModel):
    """Body for POST /search/indexed/list. Only these fields accepted; extra fields rejected (422)."""
    model_config = ConfigDict(extra="forbid")

    org_id: Optional[str] = Field(None, max_length=255, description="Filter by org_id")
    limit: int = Field(100, ge=1, le=500, description="Max items to return")


class GenerateKeyRequest(BaseModel):
    """Input to generate API key. Key = HMAC(API_SECRET, input). Only 'input' accepted."""
    model_config = ConfigDict(extra="forbid")

    input: str = Field(..., min_length=1, max_length=500, description="e.g. org_id — key will be generated from this")


class SearchRequest(BaseModel):
    """Semantic/RAG search body. Only query and org_id accepted; extra fields rejected (422)."""
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=QUERY_MAX_LENGTH, description="Search query")
    org_id: Optional[str] = Field(None, max_length=255, description="If set, search only this org's products (MySQL org_id)")
    
    @field_validator('query')
    @classmethod
    def validate_query(cls, v: str) -> str:
        if not v or v.strip() == "":
            raise ValueError("Query can't be empty ")
        return v.strip()

class ProductResponse(BaseModel):
    org_id: Optional[str] = None
    product_id: str
    name: str
    category: Optional[str] = None
    brand: Optional[str] = None
    description: Optional[str] = None
    specifications: Optional[str] = None
    price: Optional[float] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    status: Optional[str] = None
    similarity_score: float

class RAGResponse(BaseModel):
    answer: str
    sources: list[ProductResponse]

class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None