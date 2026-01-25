import google.genai as genai
from app.core.config import settings


client = genai.Client(api_key=settings.GEMINI_API_KEY)

class GeminiClient:
    @staticmethod
    def embed(text: str) -> list[float]:
        """
        Returns a vector embedding for the input text using Gemini embeddings API.
        """
       
        response = client.models.embed_content(
            model="text-embedding-004",
            contents=text  
        )
        
        return response.embeddings[0].values