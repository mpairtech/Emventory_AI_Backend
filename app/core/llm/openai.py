from openai import OpenAI
from app.core.config import settings
from app.core.exceptions import LLMGenerationError, RateLimitError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import logging

logger = logging.getLogger(__name__)


def _get_client() -> OpenAI:
    if not settings.OPENAI_API_KEY:
        raise LLMGenerationError("OPENAI_API_KEY is not configured")
    try:
        return OpenAI(api_key=settings.OPENAI_API_KEY)
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI client: {e}")
        raise LLMGenerationError(f"Failed to initialize OpenAI client: {e}")


class OpenAIClient:

    @staticmethod
    @retry(
        stop=stop_after_attempt(5),  # Increased attempts for rate limit retries
        wait=wait_exponential(multiplier=2, min=4, max=60),  # Longer waits for rate limits
        retry=retry_if_exception_type((ConnectionError, TimeoutError, RateLimitError)),
        reraise=True,
    )
    def generate(prompt: str, context: str) -> str:
        """
        Mirror GeminiClient.generate behaviour but using OpenAI.
        """
        if not prompt or not prompt.strip():
            raise LLMGenerationError("Can't generate response for empty prompt")

        full_prompt = f"""Answer the user's query using ONLY the product information below. Be concise and factual.

PRODUCTS:
{context}

QUERY: {prompt}

RULES:
- Use ONLY facts from the products above. Do NOT invent anything.
- If no relevant products, say "No matching products found."
- For matches: List 1-5 products as bullets (name, key specs, why it matches).
- Be brief. No extra explanations."""

        try:
            client = _get_client()
            
            # Optimize parameters for concise, factual ecommerce answers (minimize token waste)
            # Lower temperature = less creative thinking, more focused answers
            # Lower max_tokens = forces concise responses, saves tokens
            model_name = settings.OPENAI_MODEL.lower()
            if "mini" in model_name:
                max_output_tokens = 1024  # Very concise for GPT-4.1-mini (enough for 1-5 products)
            else:
                max_output_tokens = 2048  # Concise for GPT-4.1 (enough for detailed product info)
            
            response = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a concise, factual ecommerce product assistant. Answer directly without unnecessary explanations.",
                    },
                    {
                        "role": "user",
                        "content": full_prompt,
                    },
                ],
                temperature=0.1,  # Very low = deterministic, factual, no creative thinking
                top_p=0.9,  # Focus on most likely tokens (reduces randomness)
                frequency_penalty=0.1,  # Slight penalty to avoid word repetition
                presence_penalty=0.1,  # Slight penalty to avoid topic repetition
                max_tokens=max_output_tokens,  # Strict limit to force concise answers
            )

            if not response.choices:
                raise LLMGenerationError("Empty response returned from OpenAI")

            content = response.choices[0].message.content
            if not content:
                raise LLMGenerationError("Empty message content returned from OpenAI")

            return content

        except LLMGenerationError:
            raise
        except Exception as e:
            # Check for OpenAI rate limit errors (429 status code)
            error_type = type(e).__name__
            error_msg = str(e).lower()
            
            # OpenAI SDK may raise RateLimitError or APIError with 429 status
            if "rate limit" in error_msg or "quota" in error_msg or "429" in error_msg or "RateLimitError" in error_type:
                logger.warning(f"OpenAI rate limit detected: {error_type} - {str(e)}")
                raise RateLimitError(f"LLM rate limit exceeded: {str(e)}")

            if "auth" in error_msg or "api key" in error_msg or "401" in error_msg:
                raise LLMGenerationError(f"Authentication error: {str(e)}")

            if "connection" in error_msg or "timeout" in error_msg:
                raise ConnectionError(f"Network error: {str(e)}")

            raise LLMGenerationError(f"Failed to generate response: {str(e)}")

