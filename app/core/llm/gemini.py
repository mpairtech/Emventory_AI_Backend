import google.genai as genai
from app.core.config import settings

#genai.configure(api_key=settings.GEMINI_API_KEY)

class GeminiClient:
    @staticmethod
    def embed(text: str) -> list[float]:
        res = genai.embed_content(
            model="models/text-embedding-004",
            content=text
        )
        return res["embedding"]
