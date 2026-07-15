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
    async def generate(prompt: str, context: str, language: str = "en") -> str:
        """
        Generate a RAG answer using OpenAI chat completions.

        Fully async — releases the event loop during the OpenAI HTTP call.
        Retries on transient network errors and rate limits with exponential backoff.

        Args:
            prompt: User search query.
            context: Retrieved product context.
            language: Response language — 'en' (English) or 'bn' (Bangla).
        """
        if not prompt or not prompt.strip():
            raise LLMGenerationError("Can't generate response for empty prompt")

        language_instruction = (
            "Respond entirely in Bengali (Bangla script). Do not use English."
            if language == "bn"
            else "Respond in English."
        )
        no_results_msg = (
            "কোনো পণ্য পাওয়া যায়নি।"
            if language == "bn"
            else "No matching products found."
        )
        system_content = (
            "আপনি একজন সংক্ষিপ্ত ও তথ্যনির্ভর ই-কমার্স পণ্য সহকারী। সরাসরি বাংলায় উত্তর দিন।"
            if language == "bn"
            else "You are a concise, factual ecommerce product assistant. Answer directly without unnecessary explanations."
        )

        full_prompt = f"""Answer the user's query using ONLY the product information below. Be concise and factual.

PRODUCTS:
{context}

QUERY: {prompt}

RULES:
- Use ONLY facts from the products above. Do NOT invent anything.
- For matches: List products as bullets with ONLY the product name. Do NOT include specs, processor names, RAM, price, or any technical details in the reason.
- Example format: "• [Product Name]"
- Keep each reason under 10 words. No technical details allowed in the reason.
- Be brief. No extra explanations.
- ONLY recommend products that are directly relevant to the user's query context. If a product has no clear connection to the query, exclude it entirely.
- Do NOT recommend products just because they appear in the list. Only include genuinely relevant ones.
- {language_instruction}"""

        model_name = settings.OPENAI_MODEL.lower()
        max_output_tokens = 1024 if "mini" in model_name else 2048

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
                                {"role": "system", "content": system_content},
                                {"role": "user",   "content": full_prompt},
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