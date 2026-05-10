from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
import logging
from sqlalchemy import text

from app.api.v1.router import router
from app.api.v1.speech_router import router as speech_router
from app.core.config import settings
from app.db.session import engine
from app.db.models.vector import Base
from app.core.cache.redis_client import redis_client
from app.api.v1.routers.revoke_router import router as revoke_router


from app.core.exceptions import (
    SearchServiceException,
    EmbeddingGenerationError,
    VectorSearchError,
    DatabaseError,
    LLMGenerationError,
    RateLimitError,
    ProductNotFoundError,
    SpeechToTextError,
    AudioProcessingError,
)


# LOGGING CONFIG


logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
)
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Based Search")

@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"status": "ok"}



# STARTUP / SHUTDOWN


@app.on_event("startup")
async def startup_event():
    """
    Initialize:
    - pgvector extension
    - DB tables
    - Redis (optional)
    - Debug route logging
    """

    #  Database Initialization 
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

        Base.metadata.create_all(bind=engine)
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}", exc_info=True)

    # Redis Initialization 
    #try:
        #if settings.REDIS_ENABLED:
            #if redis_client.is_available:
                #logger.info("Redis cache initialized successfully.")
           # else:
               # logger.warning("Redis unavailable — running without cache.")
       # else:
            #logger.info("Redis disabled by configuration.")
   # except Exception as e:
        #logger.warning(f"Redis initialization error: {e}")

    # -------- Route Debug Logging --------
    routes = [
        f"{list(route.methods)} {route.path}"
        for route in app.routes
        if hasattr(route, "path") and hasattr(route, "methods")
    ]
    logger.info(f"Registered routes: {routes}")


@app.on_event("shutdown")
async def shutdown_event():
    """Gracefully close Redis connection."""
    try:
        redis_client.close()
        logger.info("Redis connection closed.")
    except Exception as e:
        logger.warning(f"Error closing Redis connection: {e}")



# EXCEPTION HANDLERS


@app.exception_handler(RateLimitError)
async def rate_limit_exception_handler(request: Request, exc: RateLimitError):
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"error": "Rate limit exceeded", "detail": str(exc)},
    )


@app.exception_handler(EmbeddingGenerationError)
async def embedding_exception_handler(request: Request, exc: EmbeddingGenerationError):
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"error": "Embedding service error", "detail": str(exc)},
    )


@app.exception_handler(LLMGenerationError)
async def llm_exception_handler(request: Request, exc: LLMGenerationError):
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"error": "AI generation service error", "detail": str(exc)},
    )


@app.exception_handler(VectorSearchError)
async def vector_search_exception_handler(request: Request, exc: VectorSearchError):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "Search error", "detail": str(exc)},
    )


@app.exception_handler(DatabaseError)
async def database_exception_handler(request: Request, exc: DatabaseError):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "Database error", "detail": str(exc)},
    )


@app.exception_handler(ProductNotFoundError)
async def product_not_found_exception_handler(request: Request, exc: ProductNotFoundError):
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"error": "Product not found", "detail": str(exc)},
    )


@app.exception_handler(SearchServiceException)
async def search_service_exception_handler(request: Request, exc: SearchServiceException):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "Service error", "detail": str(exc)},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal server error",
            "detail": "An unexpected error occurred",
        },
    )




app.include_router(router, prefix="/api/v1")
app.include_router(speech_router, prefix="/api/v1")
app.include_router(revoke_router, prefix="/api/v1")

