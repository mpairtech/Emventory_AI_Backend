from __future__ import annotations

import enum
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import Column, String, Integer, DateTime, Enum as SAEnum, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.db.models.vector import Base
from app.db.session import get_db
from app.core.exceptions import DatabaseError

logger = logging.getLogger(__name__)


class PlanTier(str, enum.Enum):
    FREE      = "free"
    STARTER   = "starter"
    GROWTH    = "growth"
    UNLIMITED = "unlimited"


PLAN_LIMITS: dict[str, int | None] = {
    PlanTier.FREE:      300,
    PlanTier.STARTER:   3_000,
    PlanTier.GROWTH:    7_500,
    PlanTier.UNLIMITED: None,
}


class SearchQuota(Base):
    __tablename__ = "search_quotas"

    org_id        = Column(String(255), primary_key=True, nullable=False, index=True)
    plan = Column(
    SAEnum(PlanTier, name="plan_tier_enum", create_type=True),
    nullable=False,
    default=PlanTier.FREE,
)
    searches_used = Column(Integer, nullable=False, default=0, server_default="0")
    period_start  = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    period_end    = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at    = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return (
            f"<SearchQuota org={self.org_id!r} plan={self.plan} "
            f"used={self.searches_used} period_end={self.period_end}>"
        )


class QuotaExceededError(Exception):
    def __init__(self, org_id: str, plan: str, limit: int, used: int, resets_at: datetime):
        self.org_id    = org_id
        self.plan      = plan
        self.limit     = limit
        self.used      = used
        self.resets_at = resets_at
        super().__init__(
            f"Search quota exceeded for org '{org_id}'. "
            f"Plan: {plan}, limit: {limit}, used: {used}. "
            f"Resets at: {resets_at.isoformat()}."
        )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_tz(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class QuotaService:
    @staticmethod
    async def _get_or_create(db: AsyncSession, org_id: str) -> SearchQuota:
        result = await db.execute(
            select(SearchQuota).where(SearchQuota.org_id == org_id)
        )
        quota = result.scalar_one_or_none()

        if quota is None:
            now = _utcnow()
            quota = SearchQuota(
                org_id        = org_id,
                plan          = PlanTier.FREE,
                searches_used = 0,
                period_start  = now,
                period_end    = now + timedelta(days=30),
            )
            db.add(quota)
            try:
                await db.commit()
                await db.refresh(quota)
                logger.info("Auto-provisioned FREE quota | org=%s", org_id)
            except SQLAlchemyError:
                await db.rollback()
                result = await db.execute(
                    select(SearchQuota).where(SearchQuota.org_id == org_id)
                )
                quota = result.scalar_one_or_none()
                if quota is None:
                    raise DatabaseError(f"Failed to create quota row for org '{org_id}'")

        return quota

    @staticmethod
    async def _reset_period_if_expired(db: AsyncSession, quota: SearchQuota) -> None:
        now = _utcnow()
        period_end = _ensure_tz(quota.period_end)

        if now < period_end:
            return

        while period_end <= now:
            period_end += timedelta(days=30)

        quota.searches_used = 0
        quota.period_start  = now
        quota.period_end    = period_end

        try:
            await db.commit()
            await db.refresh(quota)
            logger.info("Quota period reset | org=%s | new_period_end=%s", quota.org_id, period_end.isoformat())
        except SQLAlchemyError as e:
            await db.rollback()
            raise DatabaseError(f"Failed to reset quota period: {e}")

    @classmethod
    async def check_and_increment(cls, db: AsyncSession, org_id: str) -> SearchQuota:
        quota = await cls._get_or_create(db, org_id)
        await cls._reset_period_if_expired(db, quota)

        limit = PLAN_LIMITS[quota.plan]

        if limit is None:
            quota.searches_used += 1
            try:
                await db.commit()
                await db.refresh(quota)
            except SQLAlchemyError as e:
                await db.rollback()
                raise DatabaseError(f"Failed to increment quota: {e}")
            return quota

        if quota.searches_used >= limit:
            raise QuotaExceededError(
                org_id    = org_id,
                plan      = quota.plan,
                limit     = limit,
                used      = quota.searches_used,
                resets_at = _ensure_tz(quota.period_end),
            )

        quota.searches_used += 1
        try:
            await db.commit()
            await db.refresh(quota)
        except SQLAlchemyError as e:
            await db.rollback()
            raise DatabaseError(f"Failed to increment quota: {e}")

        logger.debug(
            "Quota incremented | org=%s | plan=%s | used=%d/%s",
            org_id, quota.plan, quota.searches_used,
            str(limit),
        )
        return quota

    @classmethod
    async def set_plan(
        cls,
        db: AsyncSession,
        org_id: str,
        plan: PlanTier,
        reset_period: bool = True,
    ) -> SearchQuota:
        quota = await cls._get_or_create(db, org_id)
        quota.plan = plan

        if reset_period:
            now = _utcnow()
            quota.searches_used = 0
            quota.period_start  = now
            quota.period_end    = now + timedelta(days=30)

        try:
            await db.commit()
            await db.refresh(quota)
            logger.info("Plan updated | org=%s | plan=%s | reset_period=%s", org_id, plan, reset_period)
        except SQLAlchemyError as e:
            await db.rollback()
            raise DatabaseError(f"Failed to update plan for org '{org_id}': {e}")

        return quota

    @classmethod
    async def get_usage(cls, db: AsyncSession, org_id: str) -> dict:
        quota = await cls._get_or_create(db, org_id)
        await cls._reset_period_if_expired(db, quota)

        limit      = PLAN_LIMITS[quota.plan]
        period_end = _ensure_tz(quota.period_end)

        return {
            "org_id":               quota.org_id,
            "plan":                 quota.plan,
            "searches_used":        quota.searches_used,
            "searches_limit":       limit,
            "searches_remaining":   max(0, limit - quota.searches_used) if limit is not None else None,
            "period_start":         _ensure_tz(quota.period_start).isoformat(),
            "period_end":           period_end.isoformat(),
            "resets_in_days":       max(0, (period_end - _utcnow()).days),
        }


async def check_search_quota(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> None:
    org_id: str | None = None
    try:
        body   = await request.json()
        org_id = body.get("org_id")
    except Exception:
        org_id = request.query_params.get("org_id")

    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="org_id is required.",
        )

    try:
        quota = await QuotaService.check_and_increment(db, org_id)
        logger.debug("Quota OK | org=%s | plan=%s | used=%d", org_id, quota.plan, quota.searches_used)

    except QuotaExceededError as e:
        logger.warning(
            "Quota EXCEEDED | org=%s | plan=%s | used=%d/%d | resets=%s",
            e.org_id, e.plan, e.used, e.limit, e.resets_at.isoformat(),
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error":             "search_quota_exceeded",
                "message":           (
                    f"You have used all {e.limit} searches on your '{e.plan}' plan. "
                    f"Upgrade or wait for the quota to reset."
                ),
                "plan":              e.plan,
                "searches_limit":    e.limit,
                "searches_used":     e.used,
                "resets_at":         e.resets_at.isoformat(),
            },
        )

    except DatabaseError as e:
        logger.error("Quota DB error | org=%s: %s", org_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify search quota. Please try again.",
        )

    except Exception as e:
        logger.error("Unexpected quota error | org=%s: %s", org_id, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during quota check.",
        )