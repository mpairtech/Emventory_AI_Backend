from app.core.llm.gemini import GeminiClient

class EmbeddingService:
    @staticmethod
    def embed(text: str) -> list[float]:
        return GeminiClient.embed(text)
