from __future__ import annotations

from app.core.config import settings
from app.core.exceptions import EmbeddingGenerationError, LLMGenerationError, RateLimitError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

@lru_cache(maxsize=1)
def _get_client():
    """
    Lazily create the Gemini client.

    This prevents the whole API from failing to start if:
    - `google-genai` isn't installed in the current environment, or
    - GEMINI_API_KEY isn't configured (only fails when calling LLM methods).
    """
    try:
        from google import genai  # type: ignore
    except Exception as e:  # pragma: no cover
        raise LLMGenerationError(
            "Gemini client dependency missing. Install `google-genai` to enable embeddings/LLM."
        ) from e

    try:
        # Prefer explicit settings key; otherwise let the SDK read env vars.
        api_key = getattr(settings, "GEMINI_API_KEY", None)
        if api_key:
            return genai.Client(api_key=api_key)  # No api_version override — SDK handles it
        return genai.Client()
    except Exception as e:  # pragma: no cover
        logger.error(f"Failed to initialize Gemini client: {e}", exc_info=True)
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
            client = _get_client()
            response = client.models.embed_content(
                model='models/gemini-embedding-001',  # Fixed: was 'models/text-embedding-004' (not available)
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
            raise LLMGenerationError("Can't generate response for empty prompt")

        try:
            client = _get_client()
            full_prompt = f"""You are a helpful ecommerce product assistant.
You must answer the user's query **only** using the product information given below.
If the products are not relevant or the information is insufficient, clearly say that you cannot find a good match.

== PRODUCT INFORMATION (CONTEXT) ==
{context}

== USER QUERY ==
{prompt}

== INSTRUCTIONS ==
- Only use facts present in the product information above. Do NOT invent specifications, prices, ratings, or brands.
- If there are no clearly relevant products, say that you could not find any good matches.
- When recommending products:
  - List 1–5 products as bullet points.
  - Mention the product name, key attributes (category, brand, important specs), and why it matches the query.
- Keep the answer concise, clear, and user-friendly."""

            response = client.models.generate_content(
                model="models/gemini-2.0-flash",  # Fixed: was 'models/gemini-flash-latest' (not a valid name)
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