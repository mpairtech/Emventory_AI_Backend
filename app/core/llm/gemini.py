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
    
    @staticmethod
    def generate(prompt: str, context: str) -> str:
        """Generate response using Gemini with retrieved context"""
        full_prompt = f"""You are a helpful product assistant. Based on the following product information, answer the user's query naturally and helpfully.

Product Information:
{context}

User Query: {prompt}

Provide a helpful answer based on the products above. If recommending products, explain why they match the query."""

        response = client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=full_prompt
        )
        
        return response.text