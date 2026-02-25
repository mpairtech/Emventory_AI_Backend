from fastapi import APIRouter, Header, HTTPException, Depends, Query, status
from typing import Optional
from app.api.v1.routers.search import router as search_router
from app.core.cache.cache_service import cache_service  

router = APIRouter()


# -----------------------------------------------
# Dependency: API Key + optional Org ID
# -----------------------------------------------
async def verify_api_key(
    x_api_key: Optional[str] = Header(None),
    x_org_id: Optional[str] = Header(None),
):
    """
    Basic API key + org_id extractor.
    You can extend this later for real validation.
    """
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key missing")

    # org_id can be None (fallback to global cache)
    return {"api_key": x_api_key, "org_id": x_org_id}


# -----------------------------------------------
# Include existing search router
# -----------------------------------------------
router.include_router(
    search_router,
    dependencies=[Depends(verify_api_key)]
)


# -----------------------------------------------
# Cache Management Endpoints
# -----------------------------------------------
@router.get("/cache/stats", summary="Get cache statistics")
def get_cache_stats(
    org_id: str | None = Query(None, description="Organization ID to check stats for"),
    _: None = Depends(verify_api_key),
):
    """
    Get Redis cache statistics.
    Returns cache hit/miss info, memory usage, TTL, etc.
    """
    stats = cache_service.get_cache_stats(org_id=org_id)
    return stats


@router.post("/cache/invalidate", summary="Invalidate cache for an organization")
def invalidate_cache(
    org_id: str = Query(..., description="Organization ID to invalidate cache for"),
    _: None = Depends(verify_api_key),
):
    """
    Manually invalidate all cached RAG responses for an organization.
    Useful when products are bulk updated/deleted.
    """
    success = cache_service.invalidate_org(org_id)
    if success:
        return {"status": "success", "message": f"Cache invalidated for org_id={org_id}"}
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to invalidate cache"
        )


@router.post("/cache/clear", summary="Clear all cache (admin only)")
def clear_all_cache(
    confirm: bool = Query(False, description="Must be true to confirm clearing all cache"),
    _: None = Depends(verify_api_key),
):
    """
    Clear ALL cache entries across all organizations.
    ⚠️ Use with caution! This affects all tenants.
    """
    if not confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must set confirm=true to clear all cache"
        )

    success = cache_service.clear_all_cache()
    if success:
        return {"status": "success", "message": "All cache cleared"}
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clear cache"
        )
