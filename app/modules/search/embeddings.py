from app.core.llm.embedding_client import EmbeddingClient

class EmbeddingService:
    @staticmethod
    def embed(text: str) -> list[float]:
        return EmbeddingClient.embed(text)
