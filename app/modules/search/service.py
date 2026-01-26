from app.modules.search.embeddings import EmbeddingService
from app.db.models.vector import ProductVector
from app.modules.search.repository import SearchRepository
from app.core.vector.pgvector import VectorStore
from app.core.llm.gemini import GeminiClient

class SearchService:

    @staticmethod
    def index_product(db, payload):
        text = f"{payload['name']} category {payload['category']} price {payload['price']}"
        embedding = EmbeddingService.embed(text)

        vector = ProductVector(
            product_id=payload["product_id"],
            embedding=embedding,
            name=payload["name"],
            category=payload["category"],
            price=payload["price"]
        )
        SearchRepository.upsert(db, vector)

    @staticmethod
    def semantic_search(db, query: str):
        embedding = EmbeddingService.embed(query)
        return VectorStore.search(db, embedding)
    
    @staticmethod
    def rag_search(db, query: str):
        """RAG: Retrieve relevant products + Generate AI answer"""
        # 1. Retrieve relevant products using vector search
        embedding = EmbeddingService.embed(query)
        results = VectorStore.search(db, embedding)
        
        # 2. Check if we found any products
        if not results:
            return {
                "answer": "I couldn't find any relevant products for your query.",
                "sources": []
            }
        
        # 3. Format context from retrieved products
        context = "\n".join([
            f"- {item['name']} (Category: {item['category']}, Price: ${item['price']}, Similarity: {item['similarity_score']:.2f})"
            for item in results
        ])
        
        # 4. Generate answer using Gemini LLM
        answer = GeminiClient.generate(query, context)
        
        return {
            "answer": answer,
            "sources": results
        }