import google.genai as genai
from app.core.config import settings
from app.core.exceptions import EmbeddingGenerationError, LLMGenerationError, RateLimitError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import logging

logger = logging.getLogger(__name__)

try:
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
except Exception as e:
    logger.error(f"Failed to initialize Gemini client: {e}")
    raise

class GeminiClient:
    
    @staticmethod
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        reraise=True
    )
    def embed(text: str) -> list[float]:
        if not text or not text.strip():
            raise EmbeddingGenerationError("Can't embed empty text")
        
        try:
            response = client.models.embed_content(
                model="text-embedding-004",
                contents=text
            )
            
            if not response.embeddings or not response.embeddings[0].values:
                raise EmbeddingGenerationError("Empty embedding returned from API")
            
            return response.embeddings[0].values
            
        except AttributeError as e:
            raise EmbeddingGenerationError(f"Invalid API response: {str(e)}")
            
        except Exception as e:
            error_msg = str(e).lower()
            
            if "rate limit" in error_msg or "quota" in error_msg or "429" in error_msg:
                raise RateLimitError(f"API rate limit exceeded: {str(e)}")
            
            if "auth" in error_msg or "api key" in error_msg or "401" in error_msg:
                raise EmbeddingGenerationError(f"Authentication error: {str(e)}")
            
            if "connection" in error_msg or "timeout" in error_msg:
                raise ConnectionError(f"Network error: {str(e)}")
            
            raise EmbeddingGenerationError(f"Failed to generate embedding: {str(e)}")
    
    @staticmethod
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        reraise=True
    )
    def generate(prompt: str, context: str) -> str:
        if not prompt or not prompt.strip():
            raise LLMGenerationError("Cannot generate response for empty prompt")
        
        try:
            full_prompt = f"""You are a helpful product assistant. Based on the following product information, answer the user's query naturally and helpfully.

Product Information:
{context}

User Query: {prompt}

Provide a helpful answer based on the products above. If recommending products, explain why they match the query."""

            response = client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=full_prompt
            )
            
            if not response.text:
                raise LLMGenerationError("Empty response returned from LLM")
            
            return response.text
            
        except AttributeError as e:
            raise LLMGenerationError(f"Invalid LLM response: {str(e)}")
            
        except Exception as e:
            error_msg = str(e).lower()
            
            if "rate limit" in error_msg or "quota" in error_msg or "429" in error_msg:
                raise RateLimitError(f"LLM rate limit exceeded: {str(e)}")
            
            if "auth" in error_msg or "api key" in error_msg or "401" in error_msg:
                raise LLMGenerationError(f"Authentication error: {str(e)}")
            
            if "connection" in error_msg or "timeout" in error_msg:
                raise ConnectionError(f"Network error: {str(e)}")
            
            raise LLMGenerationError(f"Failed to generate response: {str(e)}")