"""
Usage tracking service for call minutes and billing.

Track call minutes per user against plan limits.
Syncs usage to Stripe for metered billing.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from bson import ObjectId

from app.database import get_database
from app.models.subscription import get_plan_limits, get_plan_details

logger = logging.getLogger(__name__)


class UsageError(Exception):
    """Usage tracking error."""

    def __init__(self, message: str, code: str = "USAGE_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class UsageLimitExceeded(UsageError):
    """User has exceeded their usage limit."""

    def __init__(
        self,
        message: str,
        limit: float,
        used: float,
    ):
        super().__init__(message, "USAGE_LIMIT_EXCEEDED")
        self.limit = limit
        self.used = used


@dataclass
class UsageStats:
    """Usage statistics for a user."""

    user_id: str
    plan_id: str
    minutes_included: float
    minutes_used: float
    minutes_remaining: float
    total_calls: int
    period_start: datetime
    period_end: datetime
    is_over_limit: bool


@dataclass
class CallUsageRecord:
    """Individual call usage record."""

    call_id: str
    user_id: str
    company_id: str
    agent_id: str
    duration_seconds: int
    billable_minutes: float
    recorded_at: datetime


class UsageTracker:
    """
    Tracks call usage against subscription limits.

    Records call duration, checks limits, and syncs to Stripe
    for metered billing.
    """

    # Grace period: allow 5% overage before hard blocking
    OVERAGE_GRACE_PERCENT = 0.05

    def __init__(self, db=None):
        """Initialize usage tracker (optionally bound to a specific database)."""
        self._db = db

    async def _get_db(self):
        """Get database connection (get_database() is synchronous)."""
        if self._db is None:
            self._db = get_database()
        return self._db

    async def record_call_usage(
        self,
        user_id: str,
        call_id: str,
        duration_seconds: int,
        company_id: str | None = None,
        agent_id: str | None = None,
    ) -> CallUsageRecord:
        """
        Record usage for a completed call.

        Args:
            user_id: User ID
            call_id: Call ID
            duration_seconds: Call duration in seconds
            company_id: Company ID (optional)
            agent_id: Agent ID (optional)

        Returns:
            CallUsageRecord with recorded usage
        """
        db = await self._get_db()

        # Calculate billable minutes (round up to nearest minute)
        billable_minutes = (duration_seconds + 59) // 60  # Ceiling division

        now = datetime.utcnow()

        # Create usage record
        record = {
            "user_id": user_id,
            "call_id": call_id,
            "company_id": company_id,
            "agent_id": agent_id,
            "duration_seconds": duration_seconds,
            "billable_minutes": billable_minutes,
            "recorded_at": now,
        }

        # Insert usage record
        await db.usage_records.insert_one(record)

        # Update user's total usage
        await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$inc": {"subscription.minutes_used": billable_minutes},
                "$set": {"updated_at": now},
            },
        )

        logger.info(
            f"Recorded {billable_minutes} minutes for user {user_id}, call {call_id}"
        )

        return CallUsageRecord(
            call_id=call_id,
            user_id=user_id,
            company_id=company_id or "",
            agent_id=agent_id or "",
            duration_seconds=duration_seconds,
            billable_minutes=float(billable_minutes),
            recorded_at=now,
        )

    async def check_usage_limit(
        self,
        user_id: str,
        additional_minutes: float = 0,
    ) -> tuple[bool, UsageStats]:
        """
        Check if user is within their usage limit.

        Args:
            user_id: User ID to check
            additional_minutes: Minutes to add for check (for pre-flight)

        Returns:
            Tuple of (is_allowed, UsageStats)

        Note:
            Includes a grace period of OVERAGE_GRACE_PERCENT
            before hard blocking.
        """
        db = await self._get_db()

        user = await db.users.find_one(
            {"_id": ObjectId(user_id)},
            {"subscription": 1},
        )

        if not user:
            raise UsageError("User not found", "USER_NOT_FOUND")

        subscription = user.get("subscription", {})
        plan_id = subscription.get("plan", "free")
        limits = get_plan_limits(plan_id)

        minutes_included = float(limits.minutes_per_month)
        minutes_used = float(subscription.get("minutes_used", 0))
        projected_usage = minutes_used + additional_minutes

        # Calculate with grace period
        effective_limit = minutes_included * (1 + self.OVERAGE_GRACE_PERCENT)
        is_allowed = projected_usage <= effective_limit

        # Get billing period
        current_period_end = subscription.get("current_period_end")
        if current_period_end:
            period_end = current_period_end
            period_start = period_end - timedelta(days=30)
        else:
            period_end = datetime.utcnow() + timedelta(days=30)
            period_start = datetime.utcnow()

        stats = UsageStats(
            user_id=user_id,
            plan_id=plan_id,
            minutes_included=minutes_included,
            minutes_used=minutes_used,
            minutes_remaining=max(0, minutes_included - minutes_used),
            total_calls=await self._count_calls(user_id, period_start),
            period_start=period_start,
            period_end=period_end,
            is_over_limit=minutes_used >= minutes_included,
        )

        return is_allowed, stats

    async def _count_calls(
        self,
        user_id: str,
        since: datetime,
    ) -> int:
        """Count calls for a user since a date."""
        db = await self._get_db()
        return await db.calls.count_documents({
            "user_id": user_id,
            "created_at": {"$gte": since},
        })

    async def get_usage_stats(
        self,
        user_id: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> UsageStats:
        """
        Get detailed usage statistics for a user.

        Args:
            user_id: User ID
            start_date: Start of period (optional)
            end_date: End of period (optional)

        Returns:
            UsageStats with detailed metrics
        """
        db = await self._get_db()

        user = await db.users.find_one(
            {"_id": ObjectId(user_id)},
            {"subscription": 1},
        )

        if not user:
            raise UsageError("User not found", "USER_NOT_FOUND")

        subscription = user.get("subscription", {})
        plan_id = subscription.get("plan", "free")
        limits = get_plan_limits(plan_id)

        minutes_included = float(limits.minutes_per_month)
        minutes_used = float(subscription.get("minutes_used", 0))

        # Determine period
        current_period_end = subscription.get("current_period_end")
        if current_period_end:
            period_end = current_period_end
            period_start = period_end - timedelta(days=30)
        else:
            period_end = datetime.utcnow() + timedelta(days=30)
            period_start = datetime.utcnow()

        # Override with provided dates if given
        if start_date:
            period_start = start_date
        if end_date:
            period_end = end_date

        # Count calls in period
        total_calls = await self._count_calls(user_id, period_start)

        return UsageStats(
            user_id=user_id,
            plan_id=plan_id,
            minutes_included=minutes_included,
            minutes_used=minutes_used,
            minutes_remaining=max(0, minutes_included - minutes_used),
            total_calls=total_calls,
            period_start=period_start,
            period_end=period_end,
            is_over_limit=minutes_used >= minutes_included,
        )

    async def get_usage_breakdown(
        self,
        user_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> dict[str, Any]:
        """
        Get usage breakdown by day/company/agent.

        Args:
            user_id: User ID
            start_date: Start of period
            end_date: End of period

        Returns:
            Dictionary with usage breakdowns
        """
        db = await self._get_db()

        # Aggregate by day
        daily_pipeline = [
            {
                "$match": {
                    "user_id": user_id,
                    "recorded_at": {"$gte": start_date, "$lte": end_date},
                }
            },
            {
                "$group": {
                    "_id": {
                        "$dateToString": {
                            "format": "%Y-%m-%d",
                            "date": "$recorded_at",
                        }
                    },
                    "minutes": {"$sum": "$billable_minutes"},
                    "calls": {"$sum": 1},
                }
            },
            {"$sort": {"_id": 1}},
        ]

        # Aggregate by company
        company_pipeline = [
            {
                "$match": {
                    "user_id": user_id,
                    "recorded_at": {"$gte": start_date, "$lte": end_date},
                    "company_id": {"$ne": None},
                }
            },
            {
                "$group": {
                    "_id": "$company_id",
                    "minutes": {"$sum": "$billable_minutes"},
                    "calls": {"$sum": 1},
                }
            },
        ]

        # Aggregate by agent
        agent_pipeline = [
            {
                "$match": {
                    "user_id": user_id,
                    "recorded_at": {"$gte": start_date, "$lte": end_date},
                    "agent_id": {"$ne": None},
                }
            },
            {
                "$group": {
                    "_id": "$agent_id",
                    "minutes": {"$sum": "$billable_minutes"},
                    "calls": {"$sum": 1},
                }
            },
        ]

        daily_results = await db.usage_records.aggregate(daily_pipeline).to_list(100)
        company_results = await db.usage_records.aggregate(company_pipeline).to_list(100)
        agent_results = await db.usage_records.aggregate(agent_pipeline).to_list(100)

        return {
            "daily": [
                {"date": r["_id"], "minutes": r["minutes"], "calls": r["calls"]}
                for r in daily_results
            ],
            "by_company": [
                {"company_id": r["_id"], "minutes": r["minutes"], "calls": r["calls"]}
                for r in company_results
            ],
            "by_agent": [
                {"agent_id": r["_id"], "minutes": r["minutes"], "calls": r["calls"]}
                for r in agent_results
            ],
        }

    async def reset_monthly_usage(self, user_id: str) -> None:
        """
        Reset monthly usage counter for a user.

        Called when subscription renews.

        Args:
            user_id: User ID
        """
        db = await self._get_db()

        await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "subscription.minutes_used": 0,
                    "updated_at": datetime.utcnow(),
                }
            },
        )

        logger.info(f"Reset monthly usage for user {user_id}")

    async def sync_usage_to_stripe(
        self,
        user_id: str,
        subscription_item_id: str,
    ) -> dict[str, Any] | None:
        """
        Sync usage to Stripe for metered billing.

        Args:
            user_id: User ID
            subscription_item_id: Stripe subscription item ID

        Returns:
            Stripe usage record or None if no service
        """
        from app.services.billing.stripe_service import (
            get_stripe_service,
            StripeConfigError,
        )

        db = await self._get_db()

        # Get current usage
        user = await db.users.find_one(
            {"_id": ObjectId(user_id)},
            {"subscription": 1},
        )

        if not user:
            raise UsageError("User not found", "USER_NOT_FOUND")

        minutes_used = user.get("subscription", {}).get("minutes_used", 0)

        try:
            stripe_service = get_stripe_service()
            result = await stripe_service.report_usage(
                subscription_item_id=subscription_item_id,
                quantity=int(minutes_used),
                action="set",  # Set total, not increment
            )
            return result

        except StripeConfigError:
            logger.warning("Stripe not configured, skipping usage sync")
            return None

    async def update_plan_limits(
        self,
        user_id: str,
        new_plan_id: str,
    ) -> None:
        """
        Update user's plan limits (after upgrade/downgrade).

        Args:
            user_id: User ID
            new_plan_id: New plan identifier
        """
        db = await self._get_db()
        limits = get_plan_limits(new_plan_id)

        await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "subscription.plan": new_plan_id,
                    "subscription.minutes_included": limits.minutes_per_month,
                    "updated_at": datetime.utcnow(),
                }
            },
        )

        logger.info(f"Updated plan limits for user {user_id} to {new_plan_id}")

    async def estimate_overage_cost(
        self,
        user_id: str,
        overage_rate_cents: int = 10,  # $0.10 per minute default
    ) -> dict[str, Any]:
        """
        Estimate overage costs for a user.

        Args:
            user_id: User ID
            overage_rate_cents: Cost per overage minute in cents

        Returns:
            Dictionary with overage details
        """
        stats = await self.get_usage_stats(user_id)

        overage_minutes = max(0, stats.minutes_used - stats.minutes_included)
        overage_cost_cents = int(overage_minutes * overage_rate_cents)

        return {
            "minutes_included": stats.minutes_included,
            "minutes_used": stats.minutes_used,
            "overage_minutes": overage_minutes,
            "overage_rate_cents": overage_rate_cents,
            "overage_cost_cents": overage_cost_cents,
            "overage_cost_formatted": f"${overage_cost_cents / 100:.2f}",
        }


# Global instance
_usage_tracker: UsageTracker | None = None


def get_usage_tracker() -> UsageTracker:
    """Get or create global usage tracker instance."""
    global _usage_tracker
    if _usage_tracker is None:
        _usage_tracker = UsageTracker()
    return _usage_tracker


async def check_can_make_call(user_id: str) -> bool:
    """
    Quick check if user can make a call.

    Utility function for use before call initiation.

    Args:
        user_id: User ID

    Returns:
        True if user has minutes remaining
    """
    tracker = get_usage_tracker()
    can_call, _ = await tracker.check_usage_limit(user_id, additional_minutes=1)
    return can_call
