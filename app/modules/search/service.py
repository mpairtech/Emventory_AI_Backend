from __future__ import annotations
 
import asyncio
import json
import logging
import math
import re
from typing import Any, Dict, List, Optional, Set
 
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
 
from app.core.cache.cache_service import cache_service
from app.core.config import settings
from app.core.exceptions import DatabaseError, ProductNotFoundError
from app.core.llm.gemini import GeminiClient
from app.core.llm.openai import OpenAIClient
from app.core.vector.pgvector import VectorStore
from app.db.models.vector import ProductVector
from app.modules.search.embeddings import EmbeddingService
from app.modules.search.repository import SearchRepository
 
logger = logging.getLogger(__name__)
 
_SYNONYM_MAP: Dict[str, Set[str]] = {}
 
# ---------------------------------------------------------------------------
# Async OpenAI singleton for filter extraction
# ---------------------------------------------------------------------------
 
_async_filter_client: AsyncOpenAI | None = None
 
 
def _get_filter_client() -> AsyncOpenAI:
    global _async_filter_client
    if _async_filter_client is None:
        _async_filter_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _async_filter_client
 
 
class SearchService:
 
    # ============================================================
    # QUERY PREPARATION  (pure CPU — synchronous, no change needed)
    # ============================================================
 
    @staticmethod
    def _normalize_query(query: str) -> str:
        if not query:
            return ""
        q = query.strip().lower()
        q = re.sub(r"\s+", " ", q)
        return q
 
    @staticmethod
    def _expand_with_synonyms(words: Set[str]) -> Set[str]:
        if not words:
            return set()
        if not _SYNONYM_MAP:
            return set(words)
        expanded: Set[str] = set(words)
        for w in list(words):
            key = w.lower().replace("-", "")
            for base, group in _SYNONYM_MAP.items():
                if key == base.replace("-", "") or key in group:
                    expanded.update(group)
        return expanded
 
    @staticmethod
    def _prepare_query_text(raw_query: str) -> str:
        normalized = SearchService._normalize_query(raw_query)
        if not normalized:
            return ""
        words = set(normalized.split())
        expanded = SearchService._expand_with_synonyms(words)
        return " ".join(sorted(expanded))
 
    # ============================================================
    # PHASE 1 — AUTO FILTER EXTRACTION  (async — calls OpenAI)
    # ============================================================
 
    @staticmethod
    async def extract_filters_from_query(query: str) -> dict:
        """
        Auto-extract structured filters from natural-language query using LLM.
        Async: releases the event loop during the OpenAI HTTP call.
        """
        try:
            client = _get_filter_client()
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{
                    "role": "user",
                    "content": f"""Extract search filters from this product search query as JSON.
 
Query: "{query}"
 
Return only a JSON object with these optional fields:
{{
  "price_max": number or null,
  "price_min": number or null,
  "category": string or null,
  "brand": string or null,
  "status": string or null
}}
 
Examples:
"laptop under $1000" → {{"price_max": 1000}}
"Samsung phones above $500" → {{"brand": "Samsung", "price_min": 500}}
"Dell laptops between $500 and $900" → {{"brand": "Dell", "price_min": 500, "price_max": 900}}
"active Sony headphones" → {{"brand": "Sony", "status": "ACTIVE"}}
"best camera smartphone" → {{}}
"show me laptops" → {{"category": "Laptop"}}
 
Rules:
- Only extract what is explicitly mentioned
- For price, convert to number ("$1000" → 1000, "1000 dollar" → 1000)
- For category, use title case ("Laptop", "Smartphone", "Headphones")
- For brand, use proper case ("Dell", "Samsung", "Apple")
- If nothing to extract, return {{}}
- Return only JSON, no explanation""",
                }],
                response_format={"type": "json_object"},
                temperature=0,
            )
            extracted = json.loads(response.choices[0].message.content)
            clean = {k: v for k, v in extracted.items() if v is not None and v != ""}
            if clean:
                logger.info("Auto-extracted filters from query '%s': %s", query, clean)
            return clean
        except Exception as e:
            logger.warning("Filter extraction failed, proceeding without filters: %s", e)
            return {}
 
    @staticmethod
    def _build_filters_from_extracted(extracted: dict):
        if not extracted:
            return None
        try:
            from app.api.v1.schemas import SearchFilters
            return SearchFilters(**extracted)
        except Exception as e:
            logger.warning("Could not build SearchFilters from extracted: %s", e)
            return None
 
    # ============================================================
    # FILTER HELPER  (pure CPU — synchronous)
    # ============================================================
 
    @staticmethod
    def _apply_filters(
        results: List[Dict[str, Any]], filters
    ) -> List[Dict[str, Any]]:
        if not filters or not results:
            return results
 
        filtered = []
        for item in results:
            if filters.category:
                if (item.get("category") or "").strip().lower() != filters.category.strip().lower():
                    continue
            if filters.brand:
                if (item.get("brand") or "").strip().lower() != filters.brand.strip().lower():
                    continue
            if filters.price_max is not None:
                item_price = item.get("price")
                if item_price is not None and float(item_price) > filters.price_max:
                    continue
            if filters.price_min is not None:
                item_price = item.get("price")
                if item_price is not None and float(item_price) < filters.price_min:
                    continue
            if filters.status:
                if (item.get("status") or "").strip().upper() != filters.status.strip().upper():
                    continue
            filtered.append(item)
        return filtered
 
    # ============================================================
    # RANKING LOGIC  (pure CPU — synchronous)
    # ============================================================
 
    @staticmethod
    def _post_process_results(
        query: str,
        results: List[Dict[str, Any]],
        *,
        min_score: float = 0.25,
        max_items: int = 10,
    ) -> List[Dict[str, Any]]:
        if not results:
            return []
 
        q_norm = SearchService._normalize_query(query)
        q_words = set(q_norm.split())
        if q_words:
            q_words = SearchService._expand_with_synonyms(q_words)
 
        base_scores = [float(item.get("similarity_score", 0.0) or 0.0) for item in results]
        if not base_scores:
            return []
 
        max_base = max(base_scores)
        if max_base < 0.15:
            return []
 
        effective_min = max(min_score, max_base - 0.25)
        scored: List[Dict[str, Any]] = []
 
        for item, base in zip(results, base_scores):
            if base < effective_min:
                continue
 
            text = " ".join(
                str(item.get(k) or "") for k in
                ("name", "category", "brand", "description", "specifications")
            ).lower()
            prod_words = set(re.findall(r"\w+", text))
            overlap = len(q_words & prod_words) if q_words else 0
            lexical_bonus = 0.02 * min(overlap, 8)
 
            try:
                rating_f = float(item.get("rating") or 0.0)
            except (TypeError, ValueError):
                rating_f = 0.0
            rating_bonus = 0.03 * (rating_f - 3.0) if rating_f > 3.0 else 0.0
 
            try:
                rc = float(item.get("review_count") or 0)
            except (TypeError, ValueError):
                rc = 0.0
            review_bonus = 0.01 * math.log10(1.0 + rc) if rc > 0 else 0.0
 
            status = str(item.get("status") or "").lower()
            availability_bonus = 0.02 if status in {"active", "available", "in_stock", "in-stock"} else 0.0
 
            item["_final_score"] = base + lexical_bonus + rating_bonus + review_bonus + availability_bonus
            scored.append(item)
 
        scored.sort(key=lambda r: r.get("_final_score", 0.0), reverse=True)
        return scored[:max_items]
 
    # ============================================================
    # INDEX PRODUCT  (async)
    # ============================================================
 
    @staticmethod
    async def index_product(db: AsyncSession, payload: dict) -> None:
        text_lines = []
 
        name = (payload.get("name") or "").strip()
        if name:
            text_lines.extend([name, name, name])
        category = (payload.get("category") or "").strip()
        if category:
            text_lines += [f"Category: {category}"] * 2
        brand = (payload.get("brand") or "").strip()
        if brand:
            text_lines += [f"Brand: {brand}"] * 2
        if payload.get("price") is not None:
            text_lines.append(f"Price: {payload['price']}")
        desc = (payload.get("description") or "").strip()
        if desc:
            text_lines.append(f"Description: {desc[:400]}")
        specs = (payload.get("specifications") or "").strip()
        if specs:
            text_lines.append(f"Specifications: {specs[:300]}")
        if payload.get("rating") is not None:
            text_lines.append(f"Rating: {payload['rating']} stars")
 
        text = "\n".join(text_lines)
 
        # Async HTTP call to OpenAI embeddings
        embedding = await EmbeddingService.embed(text)
 
        vector = ProductVector(
            org_id=payload["org_id"],
            product_id=payload["product_id"],
            embedding=embedding,
            name=payload["name"],
            category=payload.get("category"),
            brand=payload.get("brand"),
            description=payload.get("description"),
            specifications=payload.get("specifications"),
            price=payload.get("price"),
            rating=payload.get("rating"),
            review_count=payload.get("review_count"),
            status=payload.get("status"),
        )
 
        # Async DB upsert
        await SearchRepository.upsert(db, vector)
 
        # cache_service is sync redis-py — wrap until migrated to redis.asyncio
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, cache_service.invalidate_org, payload["org_id"])
        logger.info("Invalidated RAG cache for org_id=%s", payload["org_id"])
 
    # ============================================================
    # SEMANTIC SEARCH  (async)
    # ============================================================
 
    @staticmethod
    async def semantic_search(
        db: AsyncSession,
        query: str,
        org_id: Optional[str] = None,
        top_k: int = 10,
        filters=None,
    ) -> List[Dict[str, Any]]:
        if not query or not query.strip():
            return []
 
        if filters is None:
            extracted = await SearchService.extract_filters_from_query(query)
            filters = SearchService._build_filters_from_extracted(extracted)
 
        prepared = SearchService._prepare_query_text(query)
        if not prepared:
            return []
 
        # Two async I/O calls — could be parallelised, but embedding must come first
        # because its output feeds the vector search.
        embedding = await EmbeddingService.embed(prepared)
        raw_results = await VectorStore.search(db, embedding, org_id=org_id)
 
        ranked = SearchService._post_process_results(
            query=prepared,
            results=raw_results or [],
            min_score=0.25,
            max_items=top_k,
        )
 
        if filters:
            ranked = SearchService._apply_filters(ranked, filters)
 
        logger.info(
            "Semantic search | org=%s | query='%s' | raw=%d | ranked=%d | top_k=%d",
            org_id, query, len(raw_results or []), len(ranked), top_k,
        )
        return ranked
 
    # ============================================================
    # RAG SEARCH  (async, cache integrated)
    # ============================================================
 
    @staticmethod
    async def rag_search(
        db: AsyncSession,
        query: str,
        org_id: Optional[str] = None,
        llm_provider: str = "gemini",
        top_k: int = 5,
        filters=None,
    ) -> dict:
        if not query or not query.strip():
            return {"answer": "Please provide a valid query.", "sources": []}
 
        provider = (llm_provider or "gemini").lower()
 
        if filters is None:
            extracted = await SearchService.extract_filters_from_query(query)
            filters = SearchService._build_filters_from_extracted(extracted)
 
        prepared_query = SearchService._prepare_query_text(query)
 
        # Cache read — sync redis-py; wrap until migrated
        loop = asyncio.get_running_loop()
        cached = await loop.run_in_executor(
            None,
            lambda: cache_service.get_rag_response(
                normalized_query=prepared_query, org_id=org_id, provider=provider
            ),
        )
 
        if cached:
            logger.info("RAG cache HIT | org=%s | provider=%s", org_id, provider)
            return cached
 
        logger.info("RAG cache MISS | org=%s | provider=%s", org_id, provider)
 
        embedding = await EmbeddingService.embed(prepared_query)
        raw_results = await VectorStore.search(db, embedding, org_id=org_id)
 
        ranked = SearchService._post_process_results(
            query=prepared_query,
            results=raw_results or [],
            min_score=0.25,
            max_items=top_k,
        )
 
        if filters:
            ranked = SearchService._apply_filters(ranked, filters)
 
        if not ranked:
            response = {"answer": "I couldn't find any relevant products for your query.", "sources": []}
            await loop.run_in_executor(
                None,
                lambda: cache_service.set_rag_response(
                    normalized_query=prepared_query,
                    response=response,
                    org_id=org_id,
                    provider=provider,
                    ttl=300,
                ),
            )
            return response
 
        # Build context string (pure CPU)
        context_parts = []
        for item in ranked:
            parts = [f"- {item['name']}"]
            if item.get("category"):
                parts.append(f"Category: {item['category']}")
            if item.get("brand"):
                parts.append(f"Brand: {item['brand']}")
            if item.get("price"):
                parts.append(f"Price: ${item['price']}")
            if item.get("description"):
                parts.append(f"Description: {item['description'][:200]}...")
            if item.get("specifications"):
                parts.append(f"Specifications: {item['specifications'][:150]}...")
            if item.get("rating"):
                parts.append(f"Rating: {item['rating']} stars")
            parts.append(f"Similarity: {item['similarity_score']:.2f}")
            context_parts.append(" ".join(parts))
        context = "\n".join(context_parts)
 
        # Async LLM call
        if provider == "openai":
            answer = await OpenAIClient.generate(query, context)
        else:
            # GeminiClient is sync — wrap in executor
            answer = await loop.run_in_executor(None, GeminiClient.generate, query, context)
 
        response = {"answer": answer, "sources": ranked}
 
        await loop.run_in_executor(
            None,
            lambda: cache_service.set_rag_response(
                normalized_query=prepared_query,
                response=response,
                org_id=org_id,
                provider=provider,
            ),
        )
 
        return response
 
    # ============================================================
    # UPDATE PRODUCT  (async)
    # ============================================================
 
    @staticmethod
    async def update_product(db: AsyncSession, payload: dict) -> None:
        org_id = payload["org_id"]
        product_id = payload["product_id"]
 
        existing = await SearchRepository.get_by_id(db, org_id, product_id)
        if not existing:
            raise ProductNotFoundError(
                f"Product '{product_id}' not found in org '{org_id}'"
            )
 
        await SearchService.index_product(db, payload)
        logger.info("Updated product | org=%s | product_id=%s", org_id, product_id)
 
    # ============================================================
    # DELETE PRODUCT  (async)
    # ============================================================
 
    @staticmethod
    async def delete_product(db: AsyncSession, org_id: str, product_id: str) -> None:
        await SearchRepository.delete(db, org_id, product_id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, cache_service.invalidate_org, org_id)
        logger.info("Deleted product | org=%s | product_id=%s", org_id, product_id)