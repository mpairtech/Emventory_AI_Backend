from app.modules.search.embeddings import EmbeddingService
from app.db.models.vector import ProductVector
from app.modules.search.repository import SearchRepository
from app.core.vector.pgvector import VectorStore
from app.core.llm.gemini import GeminiClient
from app.core.llm.openai import OpenAIClient
from app.core.cache.cache_service import cache_service

import re
import math
from typing import List, Dict, Any, Set, Optional
import logging

logger = logging.getLogger(__name__)

_SYNONYM_MAP: Dict[str, Set[str]] = {}


class SearchService:

    # ============================================================
    # QUERY PREPARATION
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
        prepared = " ".join(sorted(expanded))
        return prepared

    # ============================================================
    # FILTER HELPER
    # ============================================================

    @staticmethod
    def _apply_filters(results: List[Dict[str, Any]], filters) -> List[Dict[str, Any]]:
        """
        Apply post-retrieval filters to ranked results.
        Runs after vector ranking so similarity scores are unaffected.
        filters is a SearchFilters instance or None.
        """
        if not filters or not results:
            return results

        filtered = []
        for item in results:

            # Category (case-insensitive exact match)
            if filters.category:
                if (item.get("category") or "").strip().lower() != filters.category.strip().lower():
                    continue

            # Brand (case-insensitive exact match)
            if filters.brand:
                if (item.get("brand") or "").strip().lower() != filters.brand.strip().lower():
                    continue

            # Price max
            if filters.price_max is not None:
                item_price = item.get("price")
                if item_price is not None and float(item_price) > filters.price_max:
                    continue

            # Price min
            if filters.price_min is not None:
                item_price = item.get("price")
                if item_price is not None and float(item_price) < filters.price_min:
                    continue

            # Status (case-insensitive)
            if filters.status:
                if (item.get("status") or "").strip().upper() != filters.status.strip().upper():
                    continue

            filtered.append(item)

        return filtered

    # ============================================================
    # RANKING LOGIC
    # ============================================================

    @staticmethod
    def _post_process_results(
        query: str,
        results: List[Dict[str, Any]],
        *,
        min_score: float = 0.25,   # FIX: lowered from 0.5 → 0.25 to avoid filtering valid results
        max_items: int = 10
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

        # FIX: lowered guard from 0.30 → 0.15 to handle small datasets with lower
        # relative similarity scores (cosine similarity is density-dependent)
        if max_base < 0.15:
            return []

        # FIX: effective_min now uses min_score=0.25 instead of 0.5,
        # so results between 0.25–0.50 are no longer silently dropped
        effective_min = max(min_score, max_base - 0.25)

        scored: List[Dict[str, Any]] = []

        for item, base in zip(results, base_scores):
            if base < effective_min:
                continue

            text_parts = [
                str(item.get("name") or ""),
                str(item.get("category") or ""),
                str(item.get("brand") or ""),
                str(item.get("description") or ""),
                str(item.get("specifications") or ""),
            ]

            text = " ".join(text_parts).lower()
            prod_words = set(re.findall(r"\w+", text))

            overlap = len(q_words & prod_words) if q_words else 0
            lexical_bonus = 0.02 * min(overlap, 8)

            rating = item.get("rating") or 0.0
            try:
                rating_f = float(rating)
            except (TypeError, ValueError):
                rating_f = 0.0

            rating_bonus = 0.03 * (rating_f - 3.0) if rating_f > 3.0 else 0.0

            review_count = item.get("review_count") or 0
            try:
                rc = float(review_count)
            except (TypeError, ValueError):
                rc = 0.0

            review_bonus = 0.01 * math.log10(1.0 + rc) if rc > 0 else 0.0

            status = str(item.get("status") or "").lower()
            availability_bonus = 0.02 if status in {"active", "available", "in_stock", "in-stock"} else 0.0

            item["_final_score"] = (
                base
                + lexical_bonus
                + rating_bonus
                + review_bonus
                + availability_bonus
            )

            scored.append(item)

        scored.sort(key=lambda r: r.get("_final_score", 0.0), reverse=True)
        return scored[:max_items]

    # ============================================================
    # INDEX PRODUCT (with org invalidation)
    # ============================================================

    @staticmethod
    def index_product(db, payload):
        text_lines = []

        name = (payload.get("name") or "").strip()
        if name:
            text_lines.extend([name, name, name])

        category = (payload.get("category") or "").strip()
        if category:
            text_lines.append(f"Category: {category}")
            text_lines.append(f"Category: {category}")

        brand = (payload.get("brand") or "").strip()
        if brand:
            text_lines.append(f"Brand: {brand}")
            text_lines.append(f"Brand: {brand}")

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
        embedding = EmbeddingService.embed(text)

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

        SearchRepository.upsert(db, vector)

        # Invalidate entire org cache on new index
        cache_service.invalidate_org(payload["org_id"])
        logger.info(f"Invalidated RAG cache for org_id={payload['org_id']}")

    # ============================================================
    # SEMANTIC SEARCH
    # ============================================================

    @staticmethod
    def semantic_search(
        db,
        query: str,
        org_id: Optional[str] = None,
        top_k: int = 10,
        filters=None,
    ) -> List[Dict[str, Any]]:
        """
        Pure vector similarity search with optional post-retrieval filtering.
        No LLM generation — returns ranked product list directly.
        """
        if not query or not query.strip():
            return []

        prepared = SearchService._prepare_query_text(query)
        if not prepared:
            return []

        embedding = EmbeddingService.embed(prepared)
        raw_results = VectorStore.search(db, embedding, org_id=org_id)

        # FIX: min_score lowered to 0.25 (was 0.5) — prevents valid results from
        # being silently dropped, especially with small datasets where cosine
        # similarity scores naturally fall in the 0.3–0.6 range
        ranked = SearchService._post_process_results(
            query=prepared,
            results=raw_results or [],
            min_score=0.25,
            max_items=top_k,
        )

        # Apply filters after ranking so scores are unaffected
        if filters:
            ranked = SearchService._apply_filters(ranked, filters)

        logger.info(
            f"Semantic search | org={org_id} | query='{query}' "
            f"| raw={len(raw_results or [])} | ranked={len(ranked)} | top_k={top_k}"
        )

        return ranked

    # ============================================================
    # RAG SEARCH (Cache Integrated)
    # ============================================================

    @staticmethod
    def rag_search(
        db,
        query: str,
        org_id: Optional[str] = None,
        llm_provider: str = "gemini",
        top_k: int = 5,
        filters=None,
    ):
        if not query or not query.strip():
            return {
                "answer": "Please provide a valid query.",
                "sources": []
            }

        provider = (llm_provider or "gemini").lower()

        # 1️⃣ Normalize for cache stability
        prepared_query = SearchService._prepare_query_text(query)

        # 2️⃣ Check cache
        cached = cache_service.get_rag_response(
            normalized_query=prepared_query,
            org_id=org_id,
            provider=provider,
        )

        if cached:
            logger.info(f"RAG cache HIT | org={org_id} | provider={provider}")
            return cached

        logger.info(f"RAG cache MISS | org={org_id} | provider={provider}")

        # 3️⃣ Retrieval
        embedding = EmbeddingService.embed(prepared_query)
        raw_results = VectorStore.search(db, embedding, org_id=org_id)

        # FIX: min_score lowered to 0.25 (was 0.5) — same fix as semantic_search
        ranked = SearchService._post_process_results(
            query=prepared_query,
            results=raw_results or [],
            min_score=0.25,
            max_items=top_k,
        )

        # Apply filters after ranking
        if filters:
            ranked = SearchService._apply_filters(ranked, filters)

        if not ranked:
            response = {
                "answer": "I couldn't find any relevant products for your query.",
                "sources": []
            }

            cache_service.set_rag_response(
                normalized_query=prepared_query,
                response=response,
                org_id=org_id,
                provider=provider,
                ttl=300  # shorter TTL for no-results
            )

            return response

        # 4️⃣ Context build
        context_parts = []
        for item in ranked:
            parts = [f"- {item['name']}"]

            if item.get('category'):
                parts.append(f"Category: {item['category']}")
            if item.get('brand'):
                parts.append(f"Brand: {item['brand']}")
            if item.get('price'):
                parts.append(f"Price: ${item['price']}")
            if item.get('description'):
                parts.append(f"Description: {item['description'][:200]}...")
            if item.get('specifications'):
                parts.append(f"Specifications: {item['specifications'][:150]}...")
            if item.get('rating'):
                parts.append(f"Rating: {item['rating']} stars")

            parts.append(f"Similarity: {item['similarity_score']:.2f}")
            context_parts.append(" ".join(parts))

        context = "\n".join(context_parts)

        # 5️⃣ Generation
        if provider == "openai":
            answer = OpenAIClient.generate(query, context)
        else:
            answer = GeminiClient.generate(query, context)

        response = {
            "answer": answer,
            "sources": ranked
        }

        # 6️⃣ Cache result
        cache_service.set_rag_response(
            normalized_query=prepared_query,
            response=response,
            org_id=org_id,
            provider=provider,
        )

        return response