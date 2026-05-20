from openai import AsyncOpenAI
from app.core.config import settings
from app.core.exceptions import LLMGenerationError, RateLimitError
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential, retry_if_exception_type
import logging
 
logger = logging.getLogger(__name__)
 
_async_client: AsyncOpenAI | None = None
 
 
def _get_client() -> AsyncOpenAI:
    global _async_client
    if _async_client is None:
        if not settings.OPENAI_API_KEY:
            raise LLMGenerationError("OPENAI_API_KEY is not configured")
        _async_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _async_client
 
 
class OpenAIClient:
 
    @staticmethod
    async def generate(prompt: str, context: str) -> str:
        """
        Generate a RAG answer using OpenAI chat completions.
 
        Fully async — releases the event loop during the OpenAI HTTP call.
        Retries on transient network errors and rate limits with exponential backoff.
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
 
        model_name = settings.OPENAI_MODEL.lower()
        max_output_tokens = 1024 if "mini" in model_name else 2048
 
        last_exc: Exception | None = None
 
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(5),
                wait=wait_exponential(multiplier=2, min=4, max=60),
                retry=retry_if_exception_type((ConnectionError, TimeoutError, RateLimitError)),
                reraise=True,
            ):
                with attempt:
                    try:
                        client = _get_client()
                        response = await client.chat.completions.create(
                            model=settings.OPENAI_MODEL,
                            messages=[
                                {
                                    "role": "system",
                                    "content": (
                                        "You are a concise, factual ecommerce product assistant. "
                                        "Answer directly without unnecessary explanations."
                                    ),
                                },
                                {"role": "user", "content": full_prompt},
                            ],
                            temperature=0.1,
                            top_p=0.9,
                            frequency_penalty=0.1,
                            presence_penalty=0.1,
                            max_tokens=max_output_tokens,
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
                        error_type = type(e).__name__
                        error_msg = str(e).lower()
 
                        if (
                            "rate limit" in error_msg
                            or "quota" in error_msg
                            or "429" in error_msg
                            or "RateLimitError" in error_type
                        ):
                            logger.warning("OpenAI rate limit detected: %s - %s", error_type, e)
                            raise RateLimitError(f"LLM rate limit exceeded: {e}")
 
                        if "auth" in error_msg or "api key" in error_msg or "401" in error_msg:
                            raise LLMGenerationError(f"Authentication error: {e}")
 
                        if "connection" in error_msg or "timeout" in error_msg:
                            raise ConnectionError(f"Network error: {e}")
 
                        raise LLMGenerationError(f"Failed to generate response: {e}")
 
        except LLMGenerationError:
            raise
        except RateLimitError:
            raise
        except Exception as e:
            raise LLMGenerationError(f"Failed to generate response after retries: {e}")