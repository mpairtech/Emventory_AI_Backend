from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text  
from app.db.session import get_db
from app.modules.search.service import SearchService
from app.modules.search.embeddings import EmbeddingService

from app.api.v1.schemas import (
    ProductIndexRequest, 
    SearchRequest, 
    RAGResponse,
    ErrorResponse
)
import logging


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["AI Search"])


@router.post("/index", status_code=status.HTTP_201_CREATED)
def index_product(request: ProductIndexRequest, db: Session = Depends(get_db)):
    """Index a product for search with validation"""
    try:
       
        payload = request.model_dump()  
        SearchService.index_product(db, payload)
        
        logger.info(f"Successfully indexed product: {request.product_id}")
        return {
            "status": "indexed",
            "product_id": request.product_id,
            "message": f"Product '{request.name}' indexed successfully"
        }
    
    except Exception as e:
        logger.error(f"Error indexing product {request.product_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to index product: {str(e)}"
        )


@router.post("/semantic")
def semantic_search(request: SearchRequest, db: Session = Depends(get_db)):
    """Vector similarity search - returns matching products"""
    try:
        results = SearchService.semantic_search(db, request.query)
        
        logger.info(f"Semantic search for '{request.query}' returned {len(results)} results")
        return {"results": results, "query": request.query}
    
    except Exception as e:
        logger.error(f"Error in semantic search: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {str(e)}"
        )


@router.post("/rag", response_model=RAGResponse)
def rag_search(request: SearchRequest, db: Session = Depends(get_db)):
    """RAG search - returns AI-generated answer with source products"""
    try:
        result = SearchService.rag_search(db, request.query)
        
        logger.info(f"RAG search for '{request.query}' completed successfully")
        return result
    
    except Exception as e:
        logger.error(f"Error in RAG search: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"RAG search failed: {str(e)}"
        )


@router.post("/debug")
def debug_search(request: SearchRequest, db: Session = Depends(get_db)):
    """Debug: See detailed similarity scores and matching"""
    try:
        query = request.query
        query_embedding = EmbeddingService.embed(query)
        
        # Convert to PostgreSQL format
        embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'
        
        # Get detailed metrics
        sql = text("""
            SELECT 
                product_id,
                name,
                category,
                price,
                1 - (embedding <=> CAST(:q AS vector)) AS similarity_score,
                embedding <-> CAST(:q AS vector) AS euclidean_distance,
                embedding <=> CAST(:q AS vector) AS cosine_distance
            FROM product_vectors
            ORDER BY embedding <=> CAST(:q AS vector)
            LIMIT 10
        """)
        
        results = db.execute(sql, {"q": embedding_str}).fetchall()
        
        # Analyze word overlap
        query_words = set(query.lower().split())
        
        debug_results = []
        for row in results:
            product_text = f"{row[1]} {row[2]}".lower()
            product_words = set(product_text.split())
            matching_words = query_words.intersection(product_words)
            
            debug_results.append({
                "product_id": row[0],
                "name": row[1],
                "category": row[2],
                "price": float(row[3]),
                "similarity_score": float(row[4]),
                "cosine_distance": float(row[6]),
                "matching_words": list(matching_words),
                "total_query_words": len(query_words),
                "total_product_words": len(product_words)
            })
        
        logger.info(f"Debug search for '{query}' completed")
        return {
            "query": query,
            "query_words": list(query_words),
            "results": debug_results
        }
    
    except Exception as e:
        logger.error(f"Error in debug search: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Debug search failed: {str(e)}"
        )