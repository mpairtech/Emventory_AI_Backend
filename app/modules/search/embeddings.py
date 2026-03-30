from app.core.config import settings
from app.core.exceptions import EmbeddingGenerationError
import logging

logger = logging.getLogger(__name__)


class EmbeddingService:

    @staticmethod
    def embed(text: str) -> list[float]:
        try:
            if not text or not text.strip():
                raise EmbeddingGenerationError("Text can't be empty")

            provider = settings.ACTIVE_PROVIDER

            if provider == "openai":
                from openai import OpenAI
                client = OpenAI(api_key=settings.OPENAI_API_KEY)
                response = client.embeddings.create(
                    model="text-embedding-3-large",  
                    input=text,
                )
                embedding = response.data[0].embedding
            else:
                from app.core.llm.gemini import GeminiClient
                embedding = GeminiClient.embed(text)

            if not embedding or len(embedding) == 0:
                raise EmbeddingGenerationError("Received empty embedding")

            return embedding

        except EmbeddingGenerationError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error in embedding service: {e}")
            raise EmbeddingGenerationError(f"Embedding service error: {str(e)}")