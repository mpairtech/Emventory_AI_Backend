from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routers.search import verify_api_key
from app.db.session import get_db
from app.modules.search.quota import PlanTier, PLAN_LIMITS, QuotaService
from app.core.exceptions import DatabaseError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/quota", tags=["Search Quota"])


class SetPlanRequest(BaseModel):
    org_id:       str      = Field(..., min_length=1, max_length=255)
    plan:         PlanTier = Field(..., description="free | starter | growth | unlimited")
    reset_period: bool     = Field(True, description="Start a fresh 30-day window? True on plan change.")


class PlanResponse(BaseModel):
    org_id:              str
    plan:                str
    searches_used:       int
    searches_limit:      Optional[int]
    searches_remaining:  Optional[int]
    period_start:        str
    period_end:          str
    resets_in_days:      int


@router.post("/plan", response_model=PlanResponse, status_code=status.HTTP_200_OK,
             summary="Set or update a tenant's search plan (called by NestJS)")
async def set_plan(
    body: SetPlanRequest,
    _: None = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    try:
        await QuotaService.set_plan(db, org_id=body.org_id, plan=body.plan, reset_period=body.reset_period)
        return await QuotaService.get_usage(db, body.org_id)
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to update plan: {e}")
    except Exception as e:
        logger.error("Unexpected error setting plan: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


@router.get("/usage", response_model=PlanResponse,
            summary="Get current quota usage for a tenant")
async def get_usage(
    org_id: str,
    _: None = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await QuotaService.get_usage(db, org_id)
    except DatabaseError as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch usage: {e}")


@router.get("/plans", summary="List all available plan tiers and their limits")
def list_plans():
    return {
        "plans": [
            {"tier": PlanTier.FREE,      "price_usd_month": 0,      "searches_per_month": PLAN_LIMITS[PlanTier.FREE]},
            {"tier": PlanTier.STARTER,   "price_usd_month": 500,    "searches_per_month": PLAN_LIMITS[PlanTier.STARTER]},
            {"tier": PlanTier.GROWTH,    "price_usd_month": 1_000,  "searches_per_month": PLAN_LIMITS[PlanTier.GROWTH]},
            {"tier": PlanTier.UNLIMITED, "price_usd_month": 2_500,  "searches_per_month": None},
        ]
    }