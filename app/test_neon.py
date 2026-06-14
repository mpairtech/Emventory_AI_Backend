import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

NEON_URL = "postgresql+asyncpg://neondb_owner:npg_9nHE2fOCpJXr@ep-nameless-paper-ao76u8a7-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb?ssl=require"

async def test():
    engine = create_async_engine(NEON_URL, echo=True)
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT version()"))
        print(result.scalar())
    await engine.dispose()

asyncio.run(test())