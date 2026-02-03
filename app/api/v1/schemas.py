from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal

# --- NestJS integration: single AI service, model-based invoke ---
AI_MODELS = Literal["rag", "semantic", "embedding", "index"]


# Max text length for embedding to avoid token limit / cost (Gemini)
EMBEDDING_TEXT_MAX_LENGTH = 8192
QUERY_MAX_LENGTH = 500


class AIInvokeInput(BaseModel):
    """Input for POST /api/v1/ai/invoke. Fields used depend on `model`."""
    org_id: Optional[str] = Field(None, max_length=255, description="Org scope (MySQL org_id). For rag/semantic: filter by org; for index: required.")
    query: Optional[str] = Field(None, min_length=1, max_length=QUERY_MAX_LENGTH, description="For model=rag or model=semantic")
    text: Optional[str] = Field(None, min_length=1, max_length=EMBEDDING_TEXT_MAX_LENGTH, description="For model=embedding")
    product_id: Optional[str] = Field(None, max_length=50, description="Product ID (MySQL product_id)")
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    category: Optional[str] = Field(None, min_length=1, max_length=100)
    price: Optional[float] = Field(None, gt=0)

    @field_validator("name", "category", mode="after")
    @classmethod
    def strip_and_reject_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        s = (v or "").strip()
        if not s:
            raise ValueError("Field cannot be only whitespace")
        return s


class AIInvokeRequest(BaseModel):
    """NestJS hits AI Backend with model + input. One service, many models."""
    model: AI_MODELS = Field(..., description="Which AI capability to run: rag, semantic, embedding, index")
    input: AIInvokeInput = Field(..., description="Model-specific input (query, text, or product fields)")


class ProductIndexRequest(BaseModel):
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

class SearchRequest(BaseModel):
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