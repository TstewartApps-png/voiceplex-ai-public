"""
Stripe webhook handlers.

Handle Stripe webhook events for subscription lifecycle.
Includes signature verification and idempotent event processing.
"""

import logging
from datetime import datetime
from typing import Any

import stripe
from bson import ObjectId
from fastapi import APIRouter, Header, HTTPException, Request, status

from app.config import get_settings
from app.database import get_database
from app.models.subscription import get_plan_limits
from app.services.billing import get_stripe_service, get_usage_tracker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# Track processed events to ensure idempotency
_processed_events: set[str] = set()
MAX_PROCESSED_EVENTS = 10000  # Limit memory usage


async def _mark_event_processed(event_id: str) -> bool:
    """
    Mark an event as processed, return False if already processed.

    Uses in-memory set for simplicity. In production, use Redis or DB.
    """
    global _processed_events

    if event_id in _processed_events:
        return False

    _processed_events.add(event_id)

    # Cleanup old events to prevent memory growth
    if len(_processed_events) > MAX_PROCESSED_EVENTS:
        # Remove oldest half
        to_remove = list(_processed_events)[: MAX_PROCESSED_EVENTS // 2]
        for e in to_remove:
            _processed_events.discard(e)

    return True


async def _get_user_by_customer_id(customer_id: str) -> dict | None:
    """Find user by Stripe customer ID."""
    db = get_database()
    return await db.users.find_one(
        {"subscription.stripe_customer_id": customer_id}
    )


async def _get_user_by_email(email: str) -> dict | None:
    """Find user by email."""
    db = get_database()
    return await db.users.find_one({"email": email})


async def _update_user_subscription(
    user_id: str,
    update_data: dict[str, Any],
) -> None:
    """Update user subscription data."""
    db = get_database()
    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {**update_data, "updated_at": datetime.utcnow()}},
    )


# =============================================================================
# Webhook Endpoint
# =============================================================================


@router.post(
    "/stripe",
    summary="Stripe webhook handler",
    description="Handle incoming Stripe webhook events",
)
async def handle_stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="Stripe-Signature"),
):
    """
    Handle Stripe webhook events.

    Verifies signature and routes to appropriate handler.
    """
    settings = get_settings()

    if not settings.stripe_webhook_secret:
        logger.warning("Stripe webhook secret not configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook not configured",
        )

    # Get raw body for signature verification
    body = await request.body()

    try:
        event = stripe.Webhook.construct_event(
            payload=body,
            sig_header=stripe_signature,
            secret=settings.stripe_webhook_secret,
        )
    except ValueError as e:
        logger.warning(f"Invalid webhook payload: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid payload",
        )
    except stripe.SignatureVerificationError as e:
        logger.warning(f"Invalid webhook signature: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid signature",
        )

    # Check idempotency
    if not await _mark_event_processed(event.id):
        logger.info(f"Event {event.id} already processed, skipping")
        return {"status": "already_processed"}

    # Route to appropriate handler
    event_type = event.type
    event_data = event.data.object

    logger.info(f"Processing Stripe webhook: {event_type} ({event.id})")

    try:
        if event_type == "checkout.session.completed":
            await _handle_checkout_completed(event_data)

        elif event_type == "customer.subscription.created":
            await _handle_subscription_created(event_data)

        elif event_type == "customer.subscription.updated":
            await _handle_subscription_updated(event_data)

        elif event_type == "customer.subscription.deleted":
            await _handle_subscription_deleted(event_data)

        elif event_type == "invoice.paid":
            await _handle_invoice_paid(event_data)

        elif event_type == "invoice.payment_failed":
            await _handle_payment_failed(event_data)

        elif event_type == "customer.subscription.trial_will_end":
            await _handle_trial_ending(event_data)

        elif event_type == "customer.created":
            await _handle_customer_created(event_data)

        else:
            logger.info(f"Unhandled event type: {event_type}")

        return {"status": "processed", "event_type": event_type}

    except Exception as e:
        logger.exception(f"Error processing webhook {event_type}: {e}")
        # Return 200 to prevent Stripe retries for our errors
        # Log error for investigation
        return {"status": "error", "message": str(e)}


# =============================================================================
# Event Handlers
# =============================================================================


async def _handle_checkout_completed(session: dict) -> None:
    """
    Handle checkout.session.completed event.

    Called when a customer completes checkout successfully.
    Links subscription to user.
    """
    customer_id = session.get("customer")
    subscription_id = session.get("subscription")
    metadata = session.get("metadata", {})

    user_id = metadata.get("user_id")
    plan_id = metadata.get("plan_id")

    logger.info(
        f"Checkout completed: customer={customer_id}, "
        f"subscription={subscription_id}, user={user_id}"
    )

    if not user_id:
        # Try to find user by customer ID or email
        customer_email = session.get("customer_details", {}).get("email")
        user = await _get_user_by_customer_id(customer_id)
        if not user and customer_email:
            user = await _get_user_by_email(customer_email)
        if user:
            user_id = str(user["_id"])

    if not user_id:
        logger.warning(f"Could not find user for checkout session {session['id']}")
        return

    # Get subscription details from Stripe
    stripe_service = get_stripe_service()
    subscription = await stripe_service.get_subscription(subscription_id)

    if not subscription:
        logger.warning(f"Could not find subscription {subscription_id}")
        return

    # Determine plan from subscription or metadata
    if not plan_id:
        plan_id = subscription.plan_id or "starter"

    limits = get_plan_limits(plan_id)

    # Update user subscription
    await _update_user_subscription(
        user_id,
        {
            "subscription.plan": plan_id,
            "subscription.status": "active",
            "subscription.stripe_customer_id": customer_id,
            "subscription.stripe_subscription_id": subscription_id,
            "subscription.minutes_included": limits.minutes_per_month,
            "subscription.minutes_used": 0,  # Reset on new subscription
            "subscription.current_period_end": subscription.current_period_end,
            "subscription.trial_ends_at": subscription.trial_end,
        },
    )

    logger.info(f"Updated user {user_id} subscription to {plan_id}")


async def _handle_subscription_created(subscription: dict) -> None:
    """
    Handle customer.subscription.created event.

    Called when a new subscription is created.
    """
    customer_id = subscription.get("customer")
    subscription_id = subscription.get("id")
    status_val = subscription.get("status")

    logger.info(
        f"Subscription created: {subscription_id}, "
        f"customer={customer_id}, status={status_val}"
    )

    # Find user
    user = await _get_user_by_customer_id(customer_id)
    if not user:
        logger.warning(f"User not found for customer {customer_id}")
        return

    user_id = str(user["_id"])

    # Get plan from subscription items
    stripe_service = get_stripe_service()
    plan_id = None

    items = subscription.get("items", {}).get("data", [])
    if items:
        price_id = items[0].get("price", {}).get("id")
        plan_id = stripe_service.get_plan_id_for_price(price_id)

    if not plan_id:
        plan_id = "starter"  # Default

    limits = get_plan_limits(plan_id)

    # Update user
    current_period_end = datetime.fromtimestamp(subscription.get("current_period_end", 0))
    trial_end = None
    if subscription.get("trial_end"):
        trial_end = datetime.fromtimestamp(subscription["trial_end"])

    await _update_user_subscription(
        user_id,
        {
            "subscription.plan": plan_id,
            "subscription.status": status_val,
            "subscription.stripe_subscription_id": subscription_id,
            "subscription.minutes_included": limits.minutes_per_month,
            "subscription.current_period_end": current_period_end,
            "subscription.trial_ends_at": trial_end,
        },
    )


async def _handle_subscription_updated(subscription: dict) -> None:
    """
    Handle customer.subscription.updated event.

    Called on plan changes, renewals, status changes.
    """
    customer_id = subscription.get("customer")
    subscription_id = subscription.get("id")
    status_val = subscription.get("status")
    cancel_at_period_end = subscription.get("cancel_at_period_end", False)

    logger.info(
        f"Subscription updated: {subscription_id}, "
        f"status={status_val}, cancel_at_period_end={cancel_at_period_end}"
    )

    # Find user
    user = await _get_user_by_customer_id(customer_id)
    if not user:
        logger.warning(f"User not found for customer {customer_id}")
        return

    user_id = str(user["_id"])

    # Get plan from subscription items
    stripe_service = get_stripe_service()
    plan_id = None

    items = subscription.get("items", {}).get("data", [])
    if items:
        price_id = items[0].get("price", {}).get("id")
        plan_id = stripe_service.get_plan_id_for_price(price_id)

    update_data = {
        "subscription.status": status_val,
        "subscription.current_period_end": datetime.fromtimestamp(
            subscription.get("current_period_end", 0)
        ),
    }

    if plan_id:
        limits = get_plan_limits(plan_id)
        update_data["subscription.plan"] = plan_id
        update_data["subscription.minutes_included"] = limits.minutes_per_month

    # Check if this is a period renewal (reset usage)
    previous_period_end = user.get("subscription", {}).get("current_period_end")
    new_period_end = datetime.fromtimestamp(subscription.get("current_period_end", 0))

    if previous_period_end and new_period_end > previous_period_end:
        # New billing period - reset usage
        update_data["subscription.minutes_used"] = 0
        logger.info(f"Reset usage for user {user_id} due to period renewal")

    await _update_user_subscription(user_id, update_data)


async def _handle_subscription_deleted(subscription: dict) -> None:
    """
    Handle customer.subscription.deleted event.

    Called when subscription is fully canceled.
    """
    customer_id = subscription.get("customer")
    subscription_id = subscription.get("id")

    logger.info(f"Subscription deleted: {subscription_id}, customer={customer_id}")

    # Find user
    user = await _get_user_by_customer_id(customer_id)
    if not user:
        logger.warning(f"User not found for customer {customer_id}")
        return

    user_id = str(user["_id"])

    # Downgrade to free plan
    free_limits = get_plan_limits("free")

    await _update_user_subscription(
        user_id,
        {
            "subscription.plan": "free",
            "subscription.status": "canceled",
            "subscription.stripe_subscription_id": None,
            "subscription.minutes_included": free_limits.minutes_per_month,
            "subscription.current_period_end": None,
            "subscription.trial_ends_at": None,
        },
    )

    logger.info(f"Downgraded user {user_id} to free plan")


async def _handle_invoice_paid(invoice: dict) -> None:
    """
    Handle invoice.paid event.

    Called when payment is successful.
    """
    customer_id = invoice.get("customer")
    subscription_id = invoice.get("subscription")
    amount_paid = invoice.get("amount_paid", 0)

    logger.info(
        f"Invoice paid: customer={customer_id}, "
        f"subscription={subscription_id}, amount={amount_paid}"
    )

    # Find user
    user = await _get_user_by_customer_id(customer_id)
    if not user:
        return

    user_id = str(user["_id"])

    # Ensure status is active
    await _update_user_subscription(
        user_id,
        {"subscription.status": "active"},
    )

    # TODO: Send payment confirmation email
    logger.info(f"Payment confirmed for user {user_id}")


async def _handle_payment_failed(invoice: dict) -> None:
    """
    Handle invoice.payment_failed event.

    Called when payment fails.
    """
    customer_id = invoice.get("customer")
    subscription_id = invoice.get("subscription")
    attempt_count = invoice.get("attempt_count", 0)

    logger.warning(
        f"Payment failed: customer={customer_id}, "
        f"subscription={subscription_id}, attempts={attempt_count}"
    )

    # Find user
    user = await _get_user_by_customer_id(customer_id)
    if not user:
        return

    user_id = str(user["_id"])

    # Update status to past_due
    await _update_user_subscription(
        user_id,
        {"subscription.status": "past_due"},
    )

    # TODO: Send payment failed email notification
    # TODO: Implement grace period logic

    logger.warning(f"User {user_id} subscription marked as past_due")


async def _handle_trial_ending(subscription: dict) -> None:
    """
    Handle customer.subscription.trial_will_end event.

    Called 3 days before trial ends.
    """
    customer_id = subscription.get("customer")
    subscription_id = subscription.get("id")
    trial_end = subscription.get("trial_end")

    logger.info(
        f"Trial ending: customer={customer_id}, "
        f"subscription={subscription_id}, ends={trial_end}"
    )

    # Find user
    user = await _get_user_by_customer_id(customer_id)
    if not user:
        return

    user_id = str(user["_id"])
    user_email = user.get("email")

    # TODO: Send trial ending email notification
    logger.info(f"Trial ending notification for user {user_id} ({user_email})")


async def _handle_customer_created(customer: dict) -> None:
    """
    Handle customer.created event.

    Called when a new Stripe customer is created.
    """
    customer_id = customer.get("id")
    email = customer.get("email")
    metadata = customer.get("metadata", {})

    logger.info(f"Customer created: {customer_id}, email={email}")

    user_id = metadata.get("voiceplex_user_id")

    if user_id:
        # Link customer to user
        await _update_user_subscription(
            user_id,
            {"subscription.stripe_customer_id": customer_id},
        )
        logger.info(f"Linked customer {customer_id} to user {user_id}")
    elif email:
        # Try to find user by email and link
        user = await _get_user_by_email(email)
        if user:
            user_id = str(user["_id"])
            await _update_user_subscription(
                user_id,
                {"subscription.stripe_customer_id": customer_id},
            )
            logger.info(f"Linked customer {customer_id} to user {user_id} by email")
