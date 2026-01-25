from app.core.llm.gemini import GeminiClient  # <-- use Gemini instead of OpenAI

class EmbeddingService:
    @staticmethod
    def embed(text: str) -> list[float]:
        return GeminiClient.embed(text)  # <-- calls Gemini API
