from app.modules.search.embeddings import EmbeddingService
from app.db.models.vector import ProductVector
from app.modules.search.repository import SearchRepository
from app.core.vector.pgvector import VectorStore

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
