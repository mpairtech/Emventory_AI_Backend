from fastapi import APIRouter, Header, HTTPException
from typing import Optional
from app.api.v1.routers.search import router as search_router

router = APIRouter()
router.include_router(search_router)


async def verify_api_key(x_api_key: Optional[str] = Header(None)):
    """
    Verify API key from request headers.
    Modify this based on your security requirements.
    """
    
    return x_api_key
    
   