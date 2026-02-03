from app.modules.search.embeddings import EmbeddingService
from app.db.models.vector import ProductVector
from app.modules.search.repository import SearchRepository
from app.core.vector.pgvector import VectorStore
from app.core.llm.gemini import GeminiClient

class SearchService:

    @staticmethod
    def index_product(db, payload):
        # Build embedding text in structured format for best semantic results
        # Format: {Name}\nCategory: {Category}\nBrand: {Brand}\nPrice: {Price}\n...
        text_lines = []
        
        # Name (required)
        text_lines.append(payload.get('name', ''))
        
        # Category
        if payload.get('category'):
            text_lines.append(f"Category: {payload['category']}")
        
        # Brand
        if payload.get('brand'):
            text_lines.append(f"Brand: {payload['brand']}")
        
        # Price
        if payload.get('price'):
            text_lines.append(f"Price: {payload['price']}")
        
        # Description
        if payload.get('description'):
            text_lines.append(f"Description: {payload['description']}")
        
        # Specifications
        if payload.get('specifications'):
            text_lines.append(f"Specifications: {payload['specifications']}")
        
        # Tags - NOT included in embedding text (only for filtering/display)
        
        # Rating
        if payload.get('rating'):
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
        embedding = EmbeddingService.embed(query)
        return VectorStore.search(db, embedding, org_id=org_id)

    @staticmethod
    def rag_search(db, query: str, org_id: str | None = None):
        """RAG: Retrieve relevant products + Generate AI answer. If org_id given, only that org's products."""
        embedding = EmbeddingService.embed(query)
        results = VectorStore.search(db, embedding, org_id=org_id)
        
        # 2. Check if we found any products
        if not results:
            return {
                "answer": "I couldn't find any relevant products for your query.",
                "sources": []
            }
        
        # 3. Format context from retrieved products (include all available fields)
        context_parts = []
        for item in results:
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
        
        # 4. Generate answer using Gemini LLM
        answer = GeminiClient.generate(query, context)
        
        return {
            "answer": answer,
            "sources": results
        }