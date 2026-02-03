from fastapi import APIRouter
from app.api.v1.routers.search import router as search_router
from app.api.v1.routers.ai_invoke import router as ai_invoke_router

router = APIRouter()
router.include_router(search_router)
router.include_router(ai_invoke_router)
