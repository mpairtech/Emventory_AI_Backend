from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.modules.search.service import SearchService

router = APIRouter(prefix="/search", tags=["AI Search"])

@router.post("/index")
def index_product(payload: dict, db: Session = Depends(get_db)):
    SearchService.index_product(db, payload)
    return {"status": "indexed"}

@router.post("/semantic")
def semantic_search(payload: dict, db: Session = Depends(get_db)):
    results = SearchService.semantic_search(db, payload["query"])
    return {
        "results": [
            {"product_id": r.product_id, "score": float(r.score)}
            for r in results
        ]
    }
