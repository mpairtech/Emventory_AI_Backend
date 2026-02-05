from app.modules.search.embeddings import EmbeddingService
from app.db.models.vector import ProductVector
from app.modules.search.repository import SearchRepository
from app.core.vector.pgvector import VectorStore
from app.core.llm.gemini import GeminiClient
import re
import math
from typing import List, Dict, Any, Set


# NOTE: For multi-tenant setups, synonyms must be org-specific.
# We keep the structure here but do NOT hardcode any domain words.
# Later you can load per-org synonym groups from DB/config and pass
# them into this module or replace this map dynamically.
_SYNONYM_MAP: Dict[str, Set[str]] = {}


class SearchService:
    @staticmethod
    def _normalize_query(query: str) -> str:
        """
        Lightweight, generic normalization:
        - strip + lowercase
        - collapse extra whitespace
        Any domain‑specific synonyms should come later from a config/DB‑driven map,
        not hardcoded here.
        """
        if not query:
            return ""

        q = query.strip().lower()
        # collapse tabs/newlines/multiple spaces
        q = re.sub(r"\s+", " ", q)
        return q

    @staticmethod
    def _expand_with_synonyms(words: Set[str]) -> Set[str]:
        """
        Expand a set of words using the in‑memory synonym map.
        In the current multi-tenant setup this is effectively a no-op
        (we just return the same set), because global synonyms would
        conflict across different orgs.
        In future, you can inject per-org synonym groups here.
        """
        if not words:
            return set()

        if not _SYNONYM_MAP:
            # No synonyms configured -> return input unchanged
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
        """
        Normalize + synonym‑expand the query before embedding.
        This improves recall for semantically similar phrases.
        """
        normalized = SearchService._normalize_query(raw_query)
        if not normalized:
            return ""

        words = set(normalized.split())
        expanded = SearchService._expand_with_synonyms(words)
        # Keep a stable order to avoid tiny embedding variability
        prepared = " ".join(sorted(expanded))
        return prepared

    @staticmethod
    def _post_process_results(query: str, results: List[Dict[str, Any]], *,
                              min_score: float = 0.5,
                              max_items: int = 10) -> List[Dict[str, Any]]:
        """
        Apply inexpensive ranking tweaks on top of vector search:
        - drop items below a similarity threshold
        - add a tiny bonus for lexical overlap of query words with product fields
        This is NOT a replacement for vector search, just a fine‑tuner.
        """
        if not results:
            return []

        # Use normalized + synonym‑expanded query words for lexical overlap
        q_norm = SearchService._normalize_query(query)
        q_words = set(q_norm.split())
        if q_words:
            q_words = SearchService._expand_with_synonyms(q_words)

        # First pass: collect base similarity scores to derive a dynamic threshold
        base_scores: List[float] = []
        for item in results:
            base = float(item.get("similarity_score", 0.0) or 0.0)
            base_scores.append(base)

        if not base_scores:
            return []

        max_base = max(base_scores)

        # If even the best result is very weak, treat as "no good match"
        if max_base < 0.30:
            return []

        # Dynamic threshold: relative to best score but never below provided min_score
        effective_min = max(min_score, max_base - 0.25)

        scored: List[Dict[str, Any]] = []
        for item, base in zip(results, base_scores):
            if base < effective_min:
                continue

            # Build simple bag‑of‑words from important fields
            text_parts = [
                str(item.get("name") or ""),
                str(item.get("category") or ""),
                str(item.get("brand") or ""),
                str(item.get("description") or ""),
                str(item.get("specifications") or ""),
            ]
            text = " ".join(text_parts).lower()
            prod_words = set(re.findall(r"\w+", text))

            # 1) Lexical overlap with (expanded) query words
            overlap = len(q_words & prod_words) if q_words else 0
            lexical_bonus = 0.02 * min(overlap, 8)  # cap to avoid huge boosts

            # 2) Rating signal (boost good ratings a bit)
            rating = item.get("rating") or 0.0
            try:
                rating_f = float(rating)
            except (TypeError, ValueError):
                rating_f = 0.0
            rating_bonus = 0.0
            if rating_f > 3.0:
                rating_bonus = 0.03 * (rating_f - 3.0)

            # 3) Review count signal (log‑scaled so big counts don't explode scores)
            review_count = item.get("review_count") or 0
            try:
                rc = float(review_count)
            except (TypeError, ValueError):
                rc = 0.0
            review_bonus = 0.0
            if rc > 0:
                review_bonus = 0.01 * math.log10(1.0 + rc)

            # 4) Availability / status signal (prefer active/in‑stock items)
            status = str(item.get("status") or "").lower()
            availability_bonus = 0.0
            if status in {"active", "available", "in_stock", "in-stock"}:
                availability_bonus = 0.02

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

    @staticmethod
    def index_product(db, payload):
        # Build embedding text in structured format for best semantic results
        # Format: {Name}\nCategory: {Category}\nBrand: {Brand}\nPrice: {Price}\n...
        text_lines = []
        
        # Name (required) – weight it slightly higher by repeating
        name = (payload.get("name") or "").strip()
        if name:
            # Repeat 3x to make product name the strongest signal
            text_lines.extend([name, name, name])
        
        # Category (slightly higher weight)
        category = (payload.get("category") or "").strip()
        if category:
            text_lines.append(f"Category: {category}")
            text_lines.append(f"Category: {category}")
        
        # Brand (slightly higher weight)
        brand = (payload.get("brand") or "").strip()
        if brand:
            text_lines.append(f"Brand: {brand}")
            text_lines.append(f"Brand: {brand}")
        
        # Price
        if payload.get("price") is not None:
            text_lines.append(f"Price: {payload['price']}")
        
        # Description (truncate to avoid noise / token waste)
        desc = (payload.get("description") or "").strip()
        if desc:
            text_lines.append(f"Description: {desc[:400]}")
        
        # Specifications (also truncated)
        specs = (payload.get("specifications") or "").strip()
        if specs:
            text_lines.append(f"Specifications: {specs[:300]}")
        
        # Tags - NOT included in embedding text (only for filtering/display)
        
        # Rating
        if payload.get("rating") is not None:
            text_lines.append(f"Rating: {payload['rating']} stars")
        
        # Join with newlines for better structure
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
            status=payload.get("status")
        )
        SearchRepository.upsert(db, vector)

    @staticmethod
    def semantic_search(db, query: str, org_id: str | None = None):
        """
        Vector search entrypoint.
        We normalize + synonym‑expand the query so semantically similar phrases map closer in embedding space.
        """
        prepared_query = SearchService._prepare_query_text(query)
        embedding = EmbeddingService.embed(prepared_query)
        raw_results = VectorStore.search(db, embedding, org_id=org_id)

        # Tune threshold & ranking here; 0.5 is a good starting point for ecommerce‑style data.
        return SearchService._post_process_results(
            query=prepared_query,
            results=raw_results or [],
            min_score=0.5,
            max_items=10,
        )

    @staticmethod
    def rag_search(db, query: str, org_id: str | None = None):
        """RAG: Retrieve relevant products + Generate AI answer. If org_id given, only that org's products."""
        prepared_query = SearchService._prepare_query_text(query)
        embedding = EmbeddingService.embed(prepared_query)
        raw_results = VectorStore.search(db, embedding, org_id=org_id)

        ranked = SearchService._post_process_results(
            query=prepared_query,
            results=raw_results or [],
            min_score=0.5,
            max_items=5,
        )

        if not ranked:
            return {
                "answer": "I couldn't find any relevant products for your query.",
                "sources": []
            }

        # 3. Format context from retrieved products (include all available fields)
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
                parts.append(f"Description: {item['description'][:200]}...")  # Truncate long descriptions
            if item.get('specifications'):
                parts.append(f"Specifications: {item['specifications'][:150]}...")
            if item.get('rating'):
                parts.append(f"Rating: {item['rating']} stars")
            parts.append(f"Similarity: {item['similarity_score']:.2f}")
            context_parts.append(" ".join(parts))
        context = "\n".join(context_parts)

        # 4. Generate answer using Gemini LLM with the ORIGINAL user query for natural phrasing
        answer = GeminiClient.generate(query, context)

        return {
            "answer": answer,
            "sources": ranked
        }