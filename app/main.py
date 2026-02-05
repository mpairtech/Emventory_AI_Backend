from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
import logging
from app.core.exceptions import (
    SearchServiceException,
    EmbeddingGenerationError,
    VectorSearchError,
    DatabaseError,
    LLMGenerationError,
    RateLimitError,
    ProductNotFoundError
)
from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine
from app.db.models.vector import Base

logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Based Search")

@app.on_event("startup")
async def init_db():
    """Initialize database: create pgvector extension and tables if they don't exist."""
    try:
        # Create pgvector extension
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        
        # Create tables
        Base.metadata.create_all(bind=engine)
        logger.info("Database initialized: pgvector extension and product_vectors table ready.")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}", exc_info=True)
        # Don't fail startup - allow manual initialization if needed

@app.exception_handler(RateLimitError)
async def rate_limit_exception_handler(request: Request, exc: RateLimitError):
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"error": "Rate limit exceeded", "detail": str(exc)}
    )

@app.exception_handler(EmbeddingGenerationError)
async def embedding_exception_handler(request: Request, exc: EmbeddingGenerationError):
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"error": "Embedding service error", "detail": str(exc)}
    )

@app.exception_handler(LLMGenerationError)
async def llm_exception_handler(request: Request, exc: LLMGenerationError):
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"error": "AI generation service error", "detail": str(exc)}
    )

@app.exception_handler(VectorSearchError)
async def vector_search_exception_handler(request: Request, exc: VectorSearchError):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "Search error", "detail": str(exc)}
    )

@app.exception_handler(DatabaseError)
async def database_exception_handler(request: Request, exc: DatabaseError):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "Database error", "detail": str(exc)}
    )

@app.exception_handler(ProductNotFoundError)
async def product_not_found_exception_handler(request: Request, exc: ProductNotFoundError):
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"error": "Product not found", "detail": str(exc)}
    )

@app.exception_handler(SearchServiceException)
async def search_service_exception_handler(request: Request, exc: SearchServiceException):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "Service error", "detail": str(exc)}
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "Internal server error", "detail": "An unexpected error occurred"}
    )

# Import router with error handling
try:
    from app.api.v1.router import router
    app.include_router(router, prefix="/api/v1")
    logger.info("Router included successfully")
except Exception as e:
    logger.error(f"Failed to import or include router: {e}", exc_info=True)

# Debug: Verify indexed route is registered
@app.on_event("startup")
async def verify_indexed_route():
    """Verify the indexed POST route is registered."""
    indexed_routes = [
        route for route in app.routes
        if hasattr(route, 'path') and hasattr(route, 'methods') 
        and '/indexed' in route.path
    ]
    for route in indexed_routes:
        logger.info(f"Indexed route found: {list(route.methods)} {route.path}")

# Debug: List all routes
@app.on_event("startup")
async def log_routes():
    """Log all registered routes for debugging."""
    routes = []
    for route in app.routes:
        if hasattr(route, 'path') and hasattr(route, 'methods'):
            routes.append(f"{list(route.methods)} {route.path}")
    logger.info(f"Registered routes: {routes}")