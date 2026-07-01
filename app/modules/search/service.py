from __future__ import annotations

import asyncio
import logging
import math
import re
from typing import Any, Dict, List, Optional, Set

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache.cache_service import cache_service
from app.core.exceptions import DatabaseError, ProductNotFoundError
from app.core.llm.gemini import GeminiClient
from app.core.llm.openai import OpenAIClient
from app.core.vector.pgvector import VectorStore
from app.db.models.vector import ProductVector

from app.modules.search.classifier import classify_and_extract, ClassificationResult
from app.modules.search.embeddings import EmbeddingService
from app.modules.search.intent_gate import is_relevant_query, OFF_TOPIC_RESPONSE  # ← NEW
from app.modules.search.reranker import rerank
from app.modules.search.repository import SearchRepository

logger = logging.getLogger(__name__)

_SYNONYM_MAP: Dict[str, Set[str]] = {}


class SearchService:

    @staticmethod
    def _normalize_query(query: str) -> str:
        if not query:
            return ""
        q = query.strip().lower()
        q = re.sub(r"\s+", " ", q)
        return q

    @staticmethod
    def _expand_with_synonyms(words: Set[str]) -> Set[str]:
        if not words or not _SYNONYM_MAP:
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

    @staticmethod
    def _build_filters_from_result(result: ClassificationResult):
        has_any = any([
            result.price_max is not None,
            result.price_min is not None,
            result.brand is not None,
            result.status is not None,
        ])
        if not has_any:
            return None
        try:
            from app.api.v1.schemas import SearchFilters
            return SearchFilters(
                price_max = result.price_max,
                price_min = result.price_min,
                brand     = result.brand,
                status    = result.status,
            )
        except Exception as e:
            logger.warning("Could not build SearchFilters from ClassificationResult: %s", e)
            return None

    @staticmethod
    def _apply_filters(
        results: List[Dict[str, Any]], filters
    ) -> List[Dict[str, Any]]:
        if not filters or not results:
            return results

        filtered = []
        for item in results:
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

    @staticmethod
    def _post_process_results(
        query: str,
        results: List[Dict[str, Any]],
        *,
        min_score: float = 0.25,
        max_items: int = 10,
        is_hybrid: bool = False,
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

        if not is_hybrid:
            if max_base < 0.15:
                return []
            effective_min = max(min_score, max_base * 0.75)
        else:
            if max_base <= 0.0:
                return []
            effective_min = max_base * 0.30

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
        embedding = await EmbeddingService.embed(text)

        vector = ProductVector(
            org_id         = payload["org_id"],
            product_id     = payload["product_id"],
            embedding      = embedding,
            name           = payload["name"],
            category       = payload.get("category"),
            brand          = payload.get("brand"),
            description    = payload.get("description"),
            specifications = payload.get("specifications"),
            price          = payload.get("price"),
            rating         = payload.get("rating"),
            review_count   = payload.get("review_count"),
            status         = payload.get("status"),
        )

        await SearchRepository.upsert(db, vector)

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, cache_service.invalidate_org, payload["org_id"])
        logger.info("Invalidated cache for org_id=%s", payload["org_id"])

    @staticmethod
    async def semantic_search(
        db: AsyncSession,
        query: str,
        org_id: Optional[str] = None,
        top_k: int = 10,
        filters=None,
    ) -> List[Dict[str, Any]]:
        # ── guard: empty query ──────────────────────────────────────────────
        if not query or not query.strip():
            return []

        # ── guard: intent gate ──────────────────────────────────────────────
        if not await is_relevant_query(query):
            logger.info("Intent gate BLOCKED | semantic_search | query=%r", query)
            return []
        # ────────────────────────────────────────────────────────────────────

        classification: ClassificationResult = await classify_and_extract(query)

        logger.info(
            "Classifier | query=%r | intent=%s | secondary=%s | type=%s | "
            "weights=(v=%.2f, b=%.2f) | bm25_query=%r | banglish=%s",
            query,
            classification.intent,
            [i.value for i in classification.secondary_intents],
            classification.query_type,
            classification.vector_weight,
            classification.bm25_weight,
            classification.bm25_query,
            classification.is_banglish,
        )

        if filters is None:
            filters = SearchService._build_filters_from_result(classification)

        prepared = SearchService._prepare_query_text(query)
        if not prepared:
            return []

        embedding = await EmbeddingService.embed(prepared)

        raw_results = await VectorStore.hybrid_search(
            db,
            embedding     = embedding,
            query         = classification.bm25_query,
            org_id        = org_id,
            top_k         = top_k * 3,
            vector_weight = classification.vector_weight,
            bm25_weight   = classification.bm25_weight,
        )

        candidates = SearchService._post_process_results(
            query     = prepared,
            results   = raw_results or [],
            min_score = 0.45,
            max_items = top_k * 2,
            is_hybrid = True,
        )

        if filters:
            candidates = SearchService._apply_filters(candidates, filters)

        if not candidates:
            return []

        reranked = await rerank(
            query      = query,
            candidates = candidates,
            top_k      = top_k,
            threshold  = 0.50,
            intent     = classification.intent,
        )

        logger.info(
            "Semantic search | org=%s | query=%r | raw=%d | candidates=%d | reranked=%d",
            org_id, query, len(raw_results or []), len(candidates), len(reranked),
        )
        return reranked

    @staticmethod
    async def rag_search(
        db: AsyncSession,
        query: str,
        org_id: Optional[str] = None,
        llm_provider: str = "gemini",
        top_k: int = 5,
        filters=None,
    ) -> dict:
        # ── guard: empty query ──────────────────────────────────────────────
        if not query or not query.strip():
            return {"answer": "Please provide a valid query.", "sources": []}

        # ── guard: intent gate ──────────────────────────────────────────────
        if not await is_relevant_query(query):
            logger.info("Intent gate BLOCKED | rag_search | query=%r", query)
            return {
                "answer": OFF_TOPIC_RESPONSE,
                "sources": [],
                "off_topic": True,
            }
        # ────────────────────────────────────────────────────────────────────

        provider = (llm_provider or "gemini").lower()

        classification: ClassificationResult = await classify_and_extract(query)

        logger.info(
            "Classifier | query=%r | intent=%s | secondary=%s | type=%s | "
            "weights=(v=%.2f, b=%.2f) | bm25_query=%r | banglish=%s",
            query,
            classification.intent,
            [i.value for i in classification.secondary_intents],
            classification.query_type,
            classification.vector_weight,
            classification.bm25_weight,
            classification.bm25_query,
            classification.is_banglish,
        )

        if filters is None:
            filters = SearchService._build_filters_from_result(classification)

        prepared_query = SearchService._prepare_query_text(query)

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

        raw_results = await VectorStore.hybrid_search(
            db,
            embedding     = embedding,
            query         = classification.bm25_query,
            org_id        = org_id,
            top_k         = top_k * 3,
            vector_weight = classification.vector_weight,
            bm25_weight   = classification.bm25_weight,
        )

        candidates = SearchService._post_process_results(
            query     = prepared_query,
            results   = raw_results or [],
            min_score = 0.50,
            max_items = top_k * 2,
            is_hybrid = True,
        )

        if filters:
            candidates = SearchService._apply_filters(candidates, filters)

        if not candidates:
            response = {
                "answer": "I couldn't find any relevant products for your query.",
                "sources": []
            }
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

        ranked = await rerank(
            query      = query,
            candidates = candidates,
            top_k      = top_k,
            threshold  = 0.50,
            intent     = classification.intent,
        )

        if not ranked:
            response = {
                "answer": "I couldn't find any relevant products for your query.",
                "sources": []
            }
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

        context_parts = []
        for item in ranked:
            parts = [f"- {item['name']}"]
            if item.get("category"):       parts.append(f"Category: {item['category']}")
            if item.get("brand"):          parts.append(f"Brand: {item['brand']}")
            if item.get("price"):          parts.append(f"Price: ${item['price']}")
            if item.get("description"):    parts.append(f"Description: {item['description'][:200]}...")
            if item.get("specifications"): parts.append(f"Specs: {item['specifications'][:150]}...")
            if item.get("rating"):         parts.append(f"Rating: {item['rating']} stars")
            if item.get("rerank_score"):   parts.append(f"Relevance: {item['rerank_score']:.2f}")
            context_parts.append(" ".join(parts))
        context = "\n".join(context_parts)

        if provider == "openai":
            answer = await OpenAIClient.generate(query, context)
        else:
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

        logger.info(
            "RAG search | org=%s | query=%r | raw=%d | candidates=%d | ranked=%d",
            org_id, query, len(raw_results or []), len(candidates), len(ranked),
        )
        return response

    @staticmethod
    async def update_product(db: AsyncSession, payload: dict) -> None:
        org_id     = payload["org_id"]
        product_id = payload["product_id"]
        existing   = await SearchRepository.get_by_id(db, org_id, product_id)
        if not existing:
            raise ProductNotFoundError(
                f"Product '{product_id}' not found in org '{org_id}'"
            )
        await SearchService.index_product(db, payload)
        logger.info("Updated product | org=%s | product_id=%s", org_id, product_id)

    @staticmethod
    async def delete_product(db: AsyncSession, org_id: str, product_id: str) -> None:
        await SearchRepository.delete(db, org_id, product_id)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, cache_service.invalidate_org, org_id)
        logger.info("Deleted product | org=%s | product_id=%s", org_id, product_id)