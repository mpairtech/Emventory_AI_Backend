from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.config import settings
 
 
def _async_database_url() -> str:
    """Convert postgresql:// → postgresql+asyncpg:// for the async driver."""
    url = settings.DATABASE_URL
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url  # already has +asyncpg or unusual scheme
 
 
engine = create_async_engine(
    _async_database_url(),
    future=True,
    pool_size=10,
    max_overflow=5,
    pool_pre_ping=True,
    # asyncpg does not support pool_recycle via keyword — use pool_pre_ping instead.
)
 
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,  # prevents lazy-load errors after commit in async context
)
 
 
async def get_db() -> AsyncSession:
    """
    FastAPI dependency that yields an AsyncSession per request.
 
    Usage in route handler:
        async def my_route(db: AsyncSession = Depends(get_db)):
            result = await db.execute(...)
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise