from openai import OpenAI
from app.core.config import settings

class EmbeddingClient:
    _client = OpenAI(api_key=settings.OPENAI_API_KEY)

    @staticmethod
    def embed(text: str) -> list[float]:
        response = EmbeddingClient._client.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        return response.data[0].embedding
