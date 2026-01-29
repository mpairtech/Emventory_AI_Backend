from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text  
from app.db.session import get_db
from app.modules.search.service import SearchService
from app.modules.search.embeddings import EmbeddingService
from app.core.exceptions import (
    SearchServiceException,
    EmbeddingGenerationError,
    VectorSearchError,
    DatabaseError,
    LLMGenerationError,
    RateLimitError
)
from app.api.v1.schemas import (
    ProductIndexRequest, 
    SearchRequest, 
    RAGResponse
)
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["AI Search"])


@router.post("/index", status_code=status.HTTP_201_CREATED)
def index_product(request: ProductIndexRequest, db: Session = Depends(get_db)):
    try:
        payload = request.model_dump()  
        SearchService.index_product(db, payload)
        
        return {
            "status": "indexed",
            "product_id": request.product_id,
            "message": f"Product '{request.name}' indexed successfully"
        }
    
    except RateLimitError as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(e)
        )
    
    except EmbeddingGenerationError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Embedding service error: {str(e)}"
        )
    
    except DatabaseError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )
    
    except SearchServiceException as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred"
        )


@router.post("/semantic")
def semantic_search(request: SearchRequest, db: Session = Depends(get_db)):
    try:
        results = SearchService.semantic_search(db, request.query)
        return {"results": results, "query": request.query}
    
    except RateLimitError as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(e)
        )
    
    except EmbeddingGenerationError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Embedding service error: {str(e)}"
        )
    
    except VectorSearchError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search error: {str(e)}"
        )
    
    except DatabaseError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )
    
    except SearchServiceException as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred"
        )


@router.post("/rag", response_model=RAGResponse)
def rag_search(request: SearchRequest, db: Session = Depends(get_db)):
    try:
        result = SearchService.rag_search(db, request.query)
        return result
    
    except RateLimitError as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(e)
        )
    
    except EmbeddingGenerationError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Embedding service error: {str(e)}"
        )
    
    except VectorSearchError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search error: {str(e)}"
        )
    
    except DatabaseError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )
    
    except LLMGenerationError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"AI generation error: {str(e)}"
        )
    
    except SearchServiceException as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred"
        )


@router.post("/debug")
def debug_search(request: SearchRequest, db: Session = Depends(get_db)):
    try:
        query = request.query
        query_embedding = EmbeddingService.embed(query)
        
        embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'
        
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
        
        return {
            "query": query,
            "query_words": list(query_words),
            "results": debug_results
        }
    
    except RateLimitError as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(e)
        )
    
    except EmbeddingGenerationError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Embedding service error: {str(e)}"
        )
    
    except DatabaseError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )
    
    except Exception as e:
        logger.error(f"Error in debug search: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Debug search failed: {str(e)}"
        )