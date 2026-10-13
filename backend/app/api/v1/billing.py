"""
Billing API endpoints for subscription and usage management.

Stripe billing endpoints for subscription lifecycle.
"""

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, Database
from app.config import get_settings
from app.models.subscription import PLANS, get_plan_details, get_plan_limits
from app.services.billing import (
    get_stripe_service,
    get_usage_tracker,
    StripeConfigError,
    StripeSubscriptionError,
    StripeCustomerError,
    UsageError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])


# =============================================================================
# Request/Response Models
# =============================================================================


class SubscriptionResponse(BaseModel):
    """Current subscription details."""

    plan: str = Field(..., description="Plan identifier")
    plan_name: str = Field(..., description="Plan display name")
    status: str = Field(..., description="Subscription status")
    minutes_included: int = Field(..., description="Minutes included in plan")
    minutes_used: float = Field(..., description="Minutes used this period")
    minutes_remaining: float = Field(..., description="Minutes remaining")
    current_period_end: datetime | None = Field(None, description="End of current billing period")
    cancel_at_period_end: bool = Field(False, description="Will cancel at period end")
    trial_ends_at: datetime | None = Field(None, description="Trial end date")
    stripe_subscription_id: str | None = Field(None, description="Stripe subscription ID")


class PlanResponse(BaseModel):
    """Plan details for display."""

    id: str
    name: str
    description: str
    price_monthly: float
    price_yearly: float
    minutes_included: int
    max_agents: int
    max_companies: int
    features: list[str]
    is_current: bool = False


class PlansListResponse(BaseModel):
    """List of available plans."""

    plans: list[PlanResponse]
    current_plan: str


class SubscribeRequest(BaseModel):
    """Request to create a subscription."""

    plan_id: str = Field(..., description="Plan to subscribe to")
    success_url: str | None = Field(None, description="Success redirect URL")
    cancel_url: str | None = Field(None, description="Cancel redirect URL")


class CheckoutResponse(BaseModel):
    """Checkout session response."""

    checkout_url: str
    session_id: str


class UpgradeDowngradeRequest(BaseModel):
    """Request to change subscription plan."""

    new_plan_id: str = Field(..., description="New plan to switch to")


class CancelRequest(BaseModel):
    """Request to cancel subscription."""

    at_period_end: bool = Field(True, description="Cancel at end of period (vs immediately)")
    reason: str | None = Field(None, description="Cancellation reason")


class PortalResponse(BaseModel):
    """Billing portal session response."""

    portal_url: str


class UsageResponse(BaseModel):
    """Usage statistics response."""

    plan: str
    minutes_included: float
    minutes_used: float
    minutes_remaining: float
    total_calls: int
    period_start: datetime
    period_end: datetime
    is_over_limit: bool
    usage_percentage: float


class UsageBreakdownResponse(BaseModel):
    """Detailed usage breakdown."""

    daily: list[dict]
    by_company: list[dict]
    by_agent: list[dict]


class InvoiceResponse(BaseModel):
    """Invoice details."""

    id: str
    amount_due: float
    amount_paid: float
    status: str
    created: datetime
    due_date: datetime | None
    hosted_url: str | None
    pdf_url: str | None


class InvoicesListResponse(BaseModel):
    """List of invoices."""

    invoices: list[InvoiceResponse]


# =============================================================================
# Plan Endpoints
# =============================================================================


@router.get(
    "/plans",
    response_model=PlansListResponse,
    summary="List available plans",
    description="Get all available subscription plans",
)
async def list_plans(
    current_user: CurrentUser,
):
    """List all available subscription plans."""
    current_plan = current_user.subscription.plan.value

    plan_responses = []
    for plan_id, plan in PLANS.items():
        plan_responses.append(
            PlanResponse(
                id=plan.id,
                name=plan.name,
                description=plan.description,
                price_monthly=plan.price_monthly_cents / 100,
                price_yearly=plan.price_yearly_cents / 100,
                minutes_included=plan.limits.minutes_per_month,
                max_agents=plan.limits.agents,
                max_companies=plan.limits.companies,
                features=plan.features,
                is_current=plan.id == current_plan,
            )
        )

    return PlansListResponse(
        plans=plan_responses,
        current_plan=current_plan,
    )


# =============================================================================
# Subscription Endpoints
# =============================================================================


@router.get(
    "/subscription",
    response_model=SubscriptionResponse,
    summary="Get current subscription",
    description="Get the current user's subscription details",
)
async def get_subscription(
    current_user: CurrentUser,
):
    """Get current subscription details."""
    sub = current_user.subscription
    plan = get_plan_details(sub.plan.value)

    minutes_remaining = max(0, sub.minutes_included - sub.minutes_used)

    return SubscriptionResponse(
        plan=sub.plan.value,
        plan_name=plan.name,
        status=sub.status.value,
        minutes_included=sub.minutes_included,
        minutes_used=sub.minutes_used,
        minutes_remaining=minutes_remaining,
        current_period_end=sub.current_period_end,
        cancel_at_period_end=False,  # Would get from Stripe
        trial_ends_at=sub.trial_ends_at,
        stripe_subscription_id=sub.stripe_subscription_id,
    )


@router.post(
    "/subscribe",
    response_model=CheckoutResponse,
    summary="Create subscription checkout",
    description="Create a Stripe checkout session for subscription",
)
async def create_subscription(
    request: SubscribeRequest,
    current_user: CurrentUser,
    db: Database,
):
    """Create checkout session for new subscription."""
    settings = get_settings()
    stripe_service = get_stripe_service()

    # Validate plan
    if request.plan_id not in PLANS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"detail": "Invalid plan", "code": "INVALID_PLAN"},
        )

    if request.plan_id == "free":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"detail": "Cannot checkout for free plan", "code": "INVALID_PLAN"},
        )

    # Get price ID for plan
    price_id = stripe_service.get_price_id_for_plan(request.plan_id)
    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "detail": "Plan not configured in Stripe",
                "code": "STRIPE_PLAN_NOT_CONFIGURED",
            },
        )

    # Get or create Stripe customer
    try:
        customer_id = current_user.subscription.stripe_customer_id

        if not customer_id:
            customer = await stripe_service.get_or_create_customer(
                email=current_user.email,
                name=current_user.name,
                user_id=current_user.id,
            )
            customer_id = customer.id

            # Store customer ID
            from bson import ObjectId
            await db.users.update_one(
                {"_id": ObjectId(current_user.id)},
                {"$set": {"subscription.stripe_customer_id": customer_id}},
            )

        # Create checkout session
        success_url = request.success_url or f"{settings.frontend_url}/billing?success=true"
        cancel_url = request.cancel_url or f"{settings.frontend_url}/billing?canceled=true"

        session = await stripe_service.create_checkout_session(
            customer_id=customer_id,
            price_id=price_id,
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "user_id": current_user.id,
                "plan_id": request.plan_id,
            },
        )

        logger.info(f"Created checkout session {session.id} for user {current_user.id}")

        return CheckoutResponse(
            checkout_url=session.url,
            session_id=session.id,
        )

    except StripeConfigError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"detail": "Billing not configured", "code": "STRIPE_NOT_CONFIGURED"},
        )
    except (StripeCustomerError, StripeSubscriptionError) as e:
        logger.error(f"Stripe error: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"detail": str(e.message), "code": e.code},
        )


@router.post(
    "/upgrade",
    response_model=SubscriptionResponse,
    summary="Upgrade subscription",
    description="Upgrade to a higher plan",
)
async def upgrade_subscription(
    request: UpgradeDowngradeRequest,
    current_user: CurrentUser,
    db: Database,
):
    """Upgrade subscription to a higher plan."""
    return await _change_subscription(request.new_plan_id, current_user, db, is_upgrade=True)


@router.post(
    "/downgrade",
    response_model=SubscriptionResponse,
    summary="Downgrade subscription",
    description="Downgrade to a lower plan",
)
async def downgrade_subscription(
    request: UpgradeDowngradeRequest,
    current_user: CurrentUser,
    db: Database,
):
    """Downgrade subscription to a lower plan."""
    return await _change_subscription(request.new_plan_id, current_user, db, is_upgrade=False)


async def _change_subscription(
    new_plan_id: str,
    current_user: CurrentUser,
    db: Database,
    is_upgrade: bool,
):
    """Internal helper to change subscription."""
    stripe_service = get_stripe_service()

    # Validate plan
    if new_plan_id not in PLANS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"detail": "Invalid plan", "code": "INVALID_PLAN"},
        )

    current_plan = current_user.subscription.plan.value
    if new_plan_id == current_plan:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"detail": "Already on this plan", "code": "SAME_PLAN"},
        )

    # Check subscription exists
    subscription_id = current_user.subscription.stripe_subscription_id
    if not subscription_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "detail": "No active subscription to modify",
                "code": "NO_SUBSCRIPTION",
            },
        )

    # Get new price ID
    if new_plan_id == "free":
        # Downgrading to free means canceling
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "detail": "Use cancel endpoint to downgrade to free",
                "code": "USE_CANCEL_FOR_FREE",
            },
        )

    price_id = stripe_service.get_price_id_for_plan(new_plan_id)
    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "detail": "Plan not configured in Stripe",
                "code": "STRIPE_PLAN_NOT_CONFIGURED",
            },
        )

    try:
        # Update subscription in Stripe
        subscription = await stripe_service.update_subscription(
            subscription_id=subscription_id,
            new_price_id=price_id,
            prorate=True,
        )

        # Update local database
        from bson import ObjectId
        new_limits = get_plan_limits(new_plan_id)

        await db.users.update_one(
            {"_id": ObjectId(current_user.id)},
            {
                "$set": {
                    "subscription.plan": new_plan_id,
                    "subscription.minutes_included": new_limits.minutes_per_month,
                    "subscription.current_period_end": subscription.current_period_end,
                    "updated_at": datetime.utcnow(),
                }
            },
        )

        plan = get_plan_details(new_plan_id)
        minutes_remaining = max(0, new_limits.minutes_per_month - current_user.subscription.minutes_used)

        action = "upgraded" if is_upgrade else "downgraded"
        logger.info(f"User {current_user.id} {action} to {new_plan_id}")

        return SubscriptionResponse(
            plan=new_plan_id,
            plan_name=plan.name,
            status=subscription.status,
            minutes_included=new_limits.minutes_per_month,
            minutes_used=current_user.subscription.minutes_used,
            minutes_remaining=minutes_remaining,
            current_period_end=subscription.current_period_end,
            cancel_at_period_end=subscription.cancel_at_period_end,
            trial_ends_at=subscription.trial_end,
            stripe_subscription_id=subscription.id,
        )

    except StripeConfigError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"detail": "Billing not configured", "code": "STRIPE_NOT_CONFIGURED"},
        )
    except StripeSubscriptionError as e:
        logger.error(f"Stripe error changing subscription: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"detail": str(e.message), "code": e.code},
        )


@router.post(
    "/cancel",
    response_model=SubscriptionResponse,
    summary="Cancel subscription",
    description="Cancel the current subscription",
)
async def cancel_subscription(
    request: CancelRequest,
    current_user: CurrentUser,
    db: Database,
):
    """Cancel subscription."""
    stripe_service = get_stripe_service()

    subscription_id = current_user.subscription.stripe_subscription_id
    if not subscription_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "detail": "No active subscription to cancel",
                "code": "NO_SUBSCRIPTION",
            },
        )

    try:
        subscription = await stripe_service.cancel_subscription(
            subscription_id=subscription_id,
            at_period_end=request.at_period_end,
        )

        # Update database
        from bson import ObjectId

        update_data = {
            "updated_at": datetime.utcnow(),
        }

        if not request.at_period_end:
            # Immediate cancellation - set to free
            update_data["subscription.plan"] = "free"
            update_data["subscription.status"] = "canceled"
            update_data["subscription.stripe_subscription_id"] = None
            update_data["subscription.minutes_included"] = 50

        await db.users.update_one(
            {"_id": ObjectId(current_user.id)},
            {"$set": update_data},
        )

        plan = get_plan_details(current_user.subscription.plan.value)

        logger.info(
            f"User {current_user.id} canceled subscription, "
            f"at_period_end={request.at_period_end}"
        )

        return SubscriptionResponse(
            plan=current_user.subscription.plan.value,
            plan_name=plan.name,
            status=subscription.status,
            minutes_included=current_user.subscription.minutes_included,
            minutes_used=current_user.subscription.minutes_used,
            minutes_remaining=max(0, current_user.subscription.minutes_included - current_user.subscription.minutes_used),
            current_period_end=subscription.current_period_end,
            cancel_at_period_end=subscription.cancel_at_period_end,
            trial_ends_at=subscription.trial_end,
            stripe_subscription_id=subscription.id,
        )

    except StripeConfigError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"detail": "Billing not configured", "code": "STRIPE_NOT_CONFIGURED"},
        )
    except StripeSubscriptionError as e:
        logger.error(f"Stripe error canceling subscription: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"detail": str(e.message), "code": e.code},
        )


@router.post(
    "/resume",
    response_model=SubscriptionResponse,
    summary="Resume subscription",
    description="Resume a subscription that was set to cancel",
)
async def resume_subscription(
    current_user: CurrentUser,
    db: Database,
):
    """Resume a subscription that was set to cancel at period end."""
    stripe_service = get_stripe_service()

    subscription_id = current_user.subscription.stripe_subscription_id
    if not subscription_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "detail": "No subscription to resume",
                "code": "NO_SUBSCRIPTION",
            },
        )

    try:
        subscription = await stripe_service.resume_subscription(subscription_id)

        plan = get_plan_details(current_user.subscription.plan.value)

        logger.info(f"User {current_user.id} resumed subscription")

        return SubscriptionResponse(
            plan=current_user.subscription.plan.value,
            plan_name=plan.name,
            status=subscription.status,
            minutes_included=current_user.subscription.minutes_included,
            minutes_used=current_user.subscription.minutes_used,
            minutes_remaining=max(0, current_user.subscription.minutes_included - current_user.subscription.minutes_used),
            current_period_end=subscription.current_period_end,
            cancel_at_period_end=subscription.cancel_at_period_end,
            trial_ends_at=subscription.trial_end,
            stripe_subscription_id=subscription.id,
        )

    except StripeConfigError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"detail": "Billing not configured", "code": "STRIPE_NOT_CONFIGURED"},
        )
    except StripeSubscriptionError as e:
        logger.error(f"Stripe error resuming subscription: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"detail": str(e.message), "code": e.code},
        )


# =============================================================================
# Usage Endpoints
# =============================================================================


@router.get(
    "/usage",
    response_model=UsageResponse,
    summary="Get usage statistics",
    description="Get current usage statistics",
)
async def get_usage(
    current_user: CurrentUser,
):
    """Get current usage statistics."""
    usage_tracker = get_usage_tracker()

    try:
        stats = await usage_tracker.get_usage_stats(current_user.id)

        usage_percentage = 0.0
        if stats.minutes_included > 0:
            usage_percentage = (stats.minutes_used / stats.minutes_included) * 100

        return UsageResponse(
            plan=stats.plan_id,
            minutes_included=stats.minutes_included,
            minutes_used=stats.minutes_used,
            minutes_remaining=stats.minutes_remaining,
            total_calls=stats.total_calls,
            period_start=stats.period_start,
            period_end=stats.period_end,
            is_over_limit=stats.is_over_limit,
            usage_percentage=round(usage_percentage, 2),
        )

    except UsageError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"detail": str(e.message), "code": e.code},
        )


@router.get(
    "/usage/breakdown",
    response_model=UsageBreakdownResponse,
    summary="Get usage breakdown",
    description="Get detailed usage breakdown by day, company, and agent",
)
async def get_usage_breakdown(
    current_user: CurrentUser,
    start_date: datetime = Query(None, description="Start date"),
    end_date: datetime = Query(None, description="End date"),
):
    """Get detailed usage breakdown."""
    usage_tracker = get_usage_tracker()

    # Default to last 30 days
    if end_date is None:
        end_date = datetime.utcnow()
    if start_date is None:
        start_date = end_date - timedelta(days=30)

    try:
        breakdown = await usage_tracker.get_usage_breakdown(
            user_id=current_user.id,
            start_date=start_date,
            end_date=end_date,
        )

        return UsageBreakdownResponse(**breakdown)

    except UsageError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"detail": str(e.message), "code": e.code},
        )


# =============================================================================
# Invoice Endpoints
# =============================================================================


@router.get(
    "/invoices",
    response_model=InvoicesListResponse,
    summary="List invoices",
    description="Get invoice history",
)
async def list_invoices(
    current_user: CurrentUser,
    limit: int = Query(10, ge=1, le=100, description="Max invoices to return"),
):
    """Get invoice history."""
    stripe_service = get_stripe_service()

    customer_id = current_user.subscription.stripe_customer_id
    if not customer_id:
        return InvoicesListResponse(invoices=[])

    try:
        invoices = await stripe_service.list_invoices(
            customer_id=customer_id,
            limit=limit,
        )

        return InvoicesListResponse(
            invoices=[
                InvoiceResponse(
                    id=inv.id,
                    amount_due=inv.amount_due / 100,
                    amount_paid=inv.amount_paid / 100,
                    status=inv.status,
                    created=inv.created,
                    due_date=inv.due_date,
                    hosted_url=inv.hosted_invoice_url,
                    pdf_url=inv.pdf_url,
                )
                for inv in invoices
            ]
        )

    except StripeConfigError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"detail": "Billing not configured", "code": "STRIPE_NOT_CONFIGURED"},
        )
    except StripeSubscriptionError as e:
        logger.error(f"Stripe error listing invoices: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"detail": str(e.message), "code": e.code},
        )


# =============================================================================
# Billing Portal
# =============================================================================


@router.post(
    "/portal",
    response_model=PortalResponse,
    summary="Get billing portal URL",
    description="Get URL to Stripe's customer billing portal",
)
async def create_billing_portal(
    current_user: CurrentUser,
):
    """Create a billing portal session for self-service management."""
    settings = get_settings()
    stripe_service = get_stripe_service()

    customer_id = current_user.subscription.stripe_customer_id
    if not customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "detail": "No billing account found",
                "code": "NO_CUSTOMER",
            },
        )

    try:
        portal_url = await stripe_service.create_billing_portal_session(
            customer_id=customer_id,
            return_url=f"{settings.frontend_url}/billing",
        )

        return PortalResponse(portal_url=portal_url)

    except StripeConfigError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"detail": "Billing not configured", "code": "STRIPE_NOT_CONFIGURED"},
        )
    except StripeSubscriptionError as e:
        logger.error(f"Stripe error creating portal: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"detail": str(e.message), "code": e.code},
        )


# Import timedelta for usage breakdown
from datetime import timedelta
