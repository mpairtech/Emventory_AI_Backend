from fastapi import APIRouter
from app.api.v1.routers.search import router as search_router

router = APIRouter()
router.include_router(search_router)
