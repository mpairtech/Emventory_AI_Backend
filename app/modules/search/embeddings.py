from openai import AsyncOpenAI
from app.core.config import settings
from app.core.exceptions import EmbeddingGenerationError
import logging
 
logger = logging.getLogger(__name__)
 
_async_openai_client: AsyncOpenAI | None = None
 
 
def _get_async_openai_client() -> AsyncOpenAI:
    global _async_openai_client
    if _async_openai_client is None:
        _async_openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _async_openai_client
 
 
class EmbeddingService:
 
    @staticmethod
    async def embed(text: str) -> list[float]:
        """
        Generate an embedding vector for `text`.
 
        Fully async — releases the event loop during the OpenAI HTTP call so
        other coroutines can execute concurrently.
        """
        try:
            if not text or not text.strip():
                raise EmbeddingGenerationError("Text can't be empty")
 
            provider = settings.ACTIVE_PROVIDER
 
            if provider == "openai":
                client = _get_async_openai_client()
                response = await client.embeddings.create(
                    model="text-embedding-3-large",
                    input=text,
                )
                embedding = response.data[0].embedding
            else:
                # Gemini embed is still sync; wrap in executor to avoid blocking.
                import asyncio
                from app.core.llm.gemini import GeminiClient
                loop = asyncio.get_running_loop()
                embedding = await loop.run_in_executor(None, GeminiClient.embed, text)
 
            if not embedding or len(embedding) == 0:
                raise EmbeddingGenerationError("Received empty embedding")
 
            return embedding
 
        except EmbeddingGenerationError:
            raise
        except Exception as e:
            logger.error("Unexpected error in embedding service: %s", e)
            raise EmbeddingGenerationError(f"Embedding service error: {e}")