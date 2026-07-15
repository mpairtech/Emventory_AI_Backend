from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional, Literal
from datetime import datetime

# Max text length for embedding to avoid token limit 
EMBEDDING_TEXT_MAX_LENGTH = 8192
QUERY_MAX_LENGTH = 500
AUDIENCE_PERSONAS = Literal[
    "students", "gamers", "professionals", "parents",
    "business_owners", "content_creators", "travelers"
]

class ProductIndexRequest(BaseModel):
    """Only these fields are accepted. Extra fields in request body are rejected (422)."""
    model_config = ConfigDict(extra="forbid")

    org_id: str = Field(..., min_length=1, max_length=255, description="Org ID (MySQL organization.org_id)")
    product_id: str = Field(..., min_length=1, max_length=50, description="Product ID (MySQL product.product_id)")
    name: str = Field(..., min_length=1, max_length=255, description="Product name")
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


class SearchFilters(BaseModel):
    """Optional post-retrieval filters. Applied after vector ranking so scores are unaffected."""
    model_config = ConfigDict(extra="forbid")

    category: Optional[str] = Field(None, max_length=255, description="Filter by product category (case-insensitive)")
    brand: Optional[str] = Field(None, max_length=255, description="Filter by brand (case-insensitive)")
    price_min: Optional[float] = Field(None, gt=0, description="Minimum price (inclusive)")
    price_max: Optional[float] = Field(None, gt=0, description="Maximum price (inclusive)")
    status: Optional[str] = Field(None, max_length=50, description="Filter by status e.g. ACTIVE, INACTIVE")


class SearchRequest(BaseModel):
    """Semantic/RAG search body."""
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, max_length=QUERY_MAX_LENGTH, description="Search query")
    org_id: Optional[str] = Field(None, max_length=255, description="If set, search only this org's products (MySQL org_id)")
    top_k: int = Field(5, ge=1, le=50, description="Number of results to return (default: 5)")
    filters: Optional[SearchFilters] = Field(None, description="Optional post-retrieval filters")
    language: Literal["en", "bn"] = Field("en", description="Response language: 'en' (English) or 'bn' (Bangla)")

    @field_validator('query')
    @classmethod
    def validate_query(cls, v: str) -> str:
        if not v or v.strip() == "":
            raise ValueError("Query can't be empty")
        return v.strip()


class CloudinaryVoiceSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cloudinary_url: str = Field(..., description="Cloudinary audio file URL")
    org_id: Optional[str] = Field(None, max_length=255)
    language_code: Optional[str] = Field(None, description="e.g. 'en', 'es'")


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
    off_topic: bool =False


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None


class R2VoiceSearchRequest(BaseModel):
    """R2-based voice search. Extra fields rejected (422)."""
    model_config = ConfigDict(extra="forbid")

    file_url: str = Field(..., description="Cloudflare R2 presigned or public URL")
    org_id: str = Field(..., max_length=255)
    language: str = Field("en", description="ISO language code e.g. 'en', 'bn'")
    top_k: int = Field(5, ge=1, le=50)
    filters: Optional[SearchFilters] = None
    provider: str = Field(None, description="LLM provider: 'openai'")


# ---------------------------------------------------------------------------
# AI Content Generation
# ---------------------------------------------------------------------------

class ProductData(BaseModel):
    """Nested product fields for content generation."""
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255)
    category: Optional[str] = Field(None, max_length=255)
    brand: Optional[str] = Field(None, max_length=255)
    specifications: list[str] = Field(default_factory=list)
    price: Optional[float] = Field(None, gt=0)

    @field_validator("name", mode="after")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Product name cannot be empty")
        return v.strip()

    @field_validator("specifications", mode="after")
    @classmethod
    def clean_specifications(cls, v: list[str]) -> list[str]:
        return [s.strip() for s in v if s and s.strip()]


class ContentGenerationRequest(BaseModel):
    """Request body for POST /api/v1/content/generate."""
    model_config = ConfigDict(extra="forbid")

    product_data: ProductData
    query: Optional[str] = Field(None, max_length=500)
    region: str = Field(..., min_length=1, max_length=100)
    language: str = Field(..., min_length=2, max_length=10)
    tone: str = Field(..., description="One of: formal, casual, persuasive")

    @field_validator("tone", mode="after")
    @classmethod
    def validate_tone(cls, v: str) -> str:
        allowed = {"formal", "casual", "persuasive"}
        v_lower = v.lower().strip()
        if v_lower not in allowed:
            raise ValueError(f"Tone must be one of: {', '.join(sorted(allowed))}")
        return v_lower

    @field_validator("language", mode="after")
    @classmethod
    def normalise_language(cls, v: str) -> str:
        return v.lower().strip()

    @field_validator("region", mode="after")
    @classmethod
    def normalise_region(cls, v: str) -> str:
        return v.upper().strip()


class GeneratedContent(BaseModel):
    """A generated text field with metadata."""
    content: str
    word_count: int
    char_count: int


class ContentGenerationResponse(BaseModel):
    """Response body from POST /api/v1/content/generate."""
    product_name: str
    language: str
    region: str
    tone: str
    description: GeneratedContent
    feature_bullets: list[str]
    provider: str = "openai"


class SocialPostRequest(BaseModel):
    product_data: ProductData
    region: str = "BD"
    language: str = "english"
    tone: Literal["formal", "casual", "persuasive"] = "casual"
    query: Optional[str] = None
    price: Optional[str] = None
    shop_address: Optional[str] = None


class SocialPostContent(BaseModel):
    post_body: str
    hashtags: list[str]
    char_count: int


class SocialPostResponse(BaseModel):
    product_name: str
    language: str
    region: str
    tone: str
    post: SocialPostContent
    provider: str


class ImproveDescriptionRequest(BaseModel):
    raw_description: str = Field(
        ...,
        min_length=10,
        description="User-written product description to improve"
    )
    tone: str = Field(
        default="formal",
        description="One of: formal, casual, persuasive"
    )
    language: str = "english"
    region: str = "BD"

class ImprovedDescriptionContent(BaseModel):
    content: str
    word_count: int
    char_count: int

class ImproveDescriptionResponse(BaseModel):
    tone: str
    language: str
    region: str
    description: ImprovedDescriptionContent
    provider: str
class SocialPostRequest(BaseModel):
    product_data: ProductData
    region: str = "BD"
    language: str = "english"
    tone: Literal["formal", "casual", "persuasive"] = "casual"
    query: Optional[str] = None
    price: Optional[str] = None
    shop_address: Optional[str] = None
    target_audience: Optional[str] = Field(
        default=None,
        description="Audience persona e.g. 'students', 'gamers', 'professionals'",
    )