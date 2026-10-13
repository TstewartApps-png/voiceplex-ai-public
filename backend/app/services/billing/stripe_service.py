"""
Stripe service for subscription and billing management.

Stripe integration for subscriptions, checkout, and billing.
Handles customer management, subscription lifecycle, and usage metering.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import stripe

from app.config import get_settings
from app.models.subscription import PLANS, get_plan_details

logger = logging.getLogger(__name__)


class StripeError(Exception):
    """Base exception for Stripe errors."""

    def __init__(self, message: str, code: str = "STRIPE_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class StripeConfigError(StripeError):
    """Stripe not configured properly."""

    def __init__(self, message: str = "Stripe is not configured"):
        super().__init__(message, "STRIPE_NOT_CONFIGURED")


class StripeCustomerError(StripeError):
    """Customer operation failed."""

    def __init__(self, message: str):
        super().__init__(message, "STRIPE_CUSTOMER_ERROR")


class StripeSubscriptionError(StripeError):
    """Subscription operation failed."""

    def __init__(self, message: str):
        super().__init__(message, "STRIPE_SUBSCRIPTION_ERROR")


@dataclass
class StripeCustomer:
    """Stripe customer data."""

    id: str
    email: str
    name: str | None
    created: datetime
    metadata: dict[str, str]


@dataclass
class StripeSubscription:
    """Stripe subscription data."""

    id: str
    customer_id: str
    status: str
    plan_id: str
    price_id: str
    current_period_start: datetime
    current_period_end: datetime
    cancel_at_period_end: bool
    canceled_at: datetime | None
    trial_end: datetime | None
    items: list[dict[str, Any]]


@dataclass
class StripeInvoice:
    """Stripe invoice data."""

    id: str
    customer_id: str
    subscription_id: str | None
    amount_due: int
    amount_paid: int
    status: str
    created: datetime
    due_date: datetime | None
    hosted_invoice_url: str | None
    pdf_url: str | None


@dataclass
class CheckoutSession:
    """Stripe checkout session."""

    id: str
    url: str
    customer_id: str | None
    subscription_id: str | None
    status: str


class StripeService:
    """
    Stripe billing service.

    Handles all Stripe operations including customers, subscriptions,
    checkout sessions, and invoices.
    """

    def __init__(self):
        """Initialize Stripe with API key."""
        settings = get_settings()
        self._api_key = settings.stripe_secret_key

        if self._api_key:
            stripe.api_key = self._api_key

        # Price ID mappings
        self._price_ids = {
            "starter": settings.stripe_price_starter,
            "growth": settings.stripe_price_growth,
            "professional": settings.stripe_price_professional,
            "agency": settings.stripe_price_agency,
        }

    def _ensure_configured(self) -> None:
        """Ensure Stripe is configured."""
        if not self._api_key:
            raise StripeConfigError()

    def get_price_id_for_plan(self, plan_id: str) -> str | None:
        """
        Get Stripe price ID for a plan.

        Args:
            plan_id: Plan identifier

        Returns:
            Stripe price ID or None
        """
        return self._price_ids.get(plan_id)

    def get_plan_id_for_price(self, price_id: str) -> str | None:
        """
        Get plan ID for a Stripe price.

        Args:
            price_id: Stripe price ID

        Returns:
            Plan ID or None
        """
        for plan, pid in self._price_ids.items():
            if pid == price_id:
                return plan
        return None

    # =========================================================================
    # Customer Management
    # =========================================================================

    async def create_customer(
        self,
        email: str,
        name: str | None = None,
        user_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> StripeCustomer:
        """
        Create a new Stripe customer.

        Args:
            email: Customer email
            name: Customer name
            user_id: VoicePlex user ID
            metadata: Additional metadata

        Returns:
            StripeCustomer with customer details
        """
        self._ensure_configured()

        try:
            customer_metadata = metadata or {}
            if user_id:
                customer_metadata["voiceplex_user_id"] = user_id

            customer = stripe.Customer.create(
                email=email,
                name=name,
                metadata=customer_metadata,
            )

            logger.info(f"Created Stripe customer {customer.id} for email {email}")

            return StripeCustomer(
                id=customer.id,
                email=customer.email,
                name=customer.name,
                created=datetime.fromtimestamp(customer.created),
                metadata=dict(customer.metadata or {}),
            )

        except stripe.StripeError as e:
            logger.error(f"Failed to create Stripe customer: {e}")
            raise StripeCustomerError(f"Failed to create customer: {e}")

    async def get_customer(self, customer_id: str) -> StripeCustomer | None:
        """
        Get Stripe customer by ID.

        Args:
            customer_id: Stripe customer ID

        Returns:
            StripeCustomer or None if not found
        """
        self._ensure_configured()

        try:
            customer = stripe.Customer.retrieve(customer_id)

            if customer.deleted:
                return None

            return StripeCustomer(
                id=customer.id,
                email=customer.email,
                name=customer.name,
                created=datetime.fromtimestamp(customer.created),
                metadata=dict(customer.metadata or {}),
            )

        except stripe.InvalidRequestError:
            return None
        except stripe.StripeError as e:
            logger.error(f"Failed to get Stripe customer: {e}")
            raise StripeCustomerError(f"Failed to get customer: {e}")

    async def update_customer(
        self,
        customer_id: str,
        email: str | None = None,
        name: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> StripeCustomer:
        """
        Update a Stripe customer.

        Args:
            customer_id: Stripe customer ID
            email: New email (optional)
            name: New name (optional)
            metadata: New metadata (optional)

        Returns:
            Updated StripeCustomer
        """
        self._ensure_configured()

        try:
            update_data = {}
            if email is not None:
                update_data["email"] = email
            if name is not None:
                update_data["name"] = name
            if metadata is not None:
                update_data["metadata"] = metadata

            customer = stripe.Customer.modify(customer_id, **update_data)

            logger.info(f"Updated Stripe customer {customer_id}")

            return StripeCustomer(
                id=customer.id,
                email=customer.email,
                name=customer.name,
                created=datetime.fromtimestamp(customer.created),
                metadata=dict(customer.metadata or {}),
            )

        except stripe.StripeError as e:
            logger.error(f"Failed to update Stripe customer: {e}")
            raise StripeCustomerError(f"Failed to update customer: {e}")

    async def get_or_create_customer(
        self,
        email: str,
        name: str | None = None,
        user_id: str | None = None,
    ) -> StripeCustomer:
        """
        Get existing customer by email or create new one.

        Args:
            email: Customer email
            name: Customer name
            user_id: VoicePlex user ID

        Returns:
            StripeCustomer
        """
        self._ensure_configured()

        try:
            # Search for existing customer
            customers = stripe.Customer.list(email=email, limit=1)

            if customers.data:
                customer = customers.data[0]
                return StripeCustomer(
                    id=customer.id,
                    email=customer.email,
                    name=customer.name,
                    created=datetime.fromtimestamp(customer.created),
                    metadata=dict(customer.metadata or {}),
                )

            # Create new customer
            return await self.create_customer(
                email=email,
                name=name,
                user_id=user_id,
            )

        except stripe.StripeError as e:
            logger.error(f"Failed to get or create customer: {e}")
            raise StripeCustomerError(f"Failed to get or create customer: {e}")

    # =========================================================================
    # Checkout Sessions
    # =========================================================================

    async def create_checkout_session(
        self,
        customer_id: str | None,
        price_id: str,
        success_url: str,
        cancel_url: str,
        customer_email: str | None = None,
        trial_days: int | None = None,
        metadata: dict[str, str] | None = None,
    ) -> CheckoutSession:
        """
        Create a Stripe Checkout session for subscription.

        Args:
            customer_id: Existing Stripe customer ID (optional)
            price_id: Stripe price ID
            success_url: URL to redirect on success
            cancel_url: URL to redirect on cancel
            customer_email: Email for new customer (if no customer_id)
            trial_days: Trial period in days (optional)
            metadata: Session metadata

        Returns:
            CheckoutSession with URL to redirect user to
        """
        self._ensure_configured()

        try:
            session_params = {
                "mode": "subscription",
                "line_items": [{"price": price_id, "quantity": 1}],
                "success_url": success_url,
                "cancel_url": cancel_url,
                "metadata": metadata or {},
            }

            if customer_id:
                session_params["customer"] = customer_id
            elif customer_email:
                session_params["customer_email"] = customer_email

            if trial_days:
                session_params["subscription_data"] = {
                    "trial_period_days": trial_days,
                }

            session = stripe.checkout.Session.create(**session_params)

            logger.info(f"Created checkout session {session.id}")

            return CheckoutSession(
                id=session.id,
                url=session.url,
                customer_id=session.customer,
                subscription_id=session.subscription,
                status=session.status,
            )

        except stripe.StripeError as e:
            logger.error(f"Failed to create checkout session: {e}")
            raise StripeSubscriptionError(f"Failed to create checkout session: {e}")

    async def get_checkout_session(self, session_id: str) -> CheckoutSession | None:
        """
        Get checkout session by ID.

        Args:
            session_id: Stripe checkout session ID

        Returns:
            CheckoutSession or None
        """
        self._ensure_configured()

        try:
            session = stripe.checkout.Session.retrieve(session_id)

            return CheckoutSession(
                id=session.id,
                url=session.url,
                customer_id=session.customer,
                subscription_id=session.subscription,
                status=session.status,
            )

        except stripe.InvalidRequestError:
            return None
        except stripe.StripeError as e:
            logger.error(f"Failed to get checkout session: {e}")
            raise StripeSubscriptionError(f"Failed to get checkout session: {e}")

    # =========================================================================
    # Subscription Management
    # =========================================================================

    async def create_subscription(
        self,
        customer_id: str,
        price_id: str,
        trial_days: int | None = None,
        metadata: dict[str, str] | None = None,
    ) -> StripeSubscription:
        """
        Create a subscription directly (without checkout).

        Args:
            customer_id: Stripe customer ID
            price_id: Stripe price ID
            trial_days: Trial period in days
            metadata: Subscription metadata

        Returns:
            StripeSubscription
        """
        self._ensure_configured()

        try:
            subscription_params = {
                "customer": customer_id,
                "items": [{"price": price_id}],
                "metadata": metadata or {},
            }

            if trial_days:
                subscription_params["trial_period_days"] = trial_days

            subscription = stripe.Subscription.create(**subscription_params)

            logger.info(f"Created subscription {subscription.id} for customer {customer_id}")

            return self._parse_subscription(subscription)

        except stripe.StripeError as e:
            logger.error(f"Failed to create subscription: {e}")
            raise StripeSubscriptionError(f"Failed to create subscription: {e}")

    async def get_subscription(self, subscription_id: str) -> StripeSubscription | None:
        """
        Get subscription by ID.

        Args:
            subscription_id: Stripe subscription ID

        Returns:
            StripeSubscription or None
        """
        self._ensure_configured()

        try:
            subscription = stripe.Subscription.retrieve(subscription_id)
            return self._parse_subscription(subscription)

        except stripe.InvalidRequestError:
            return None
        except stripe.StripeError as e:
            logger.error(f"Failed to get subscription: {e}")
            raise StripeSubscriptionError(f"Failed to get subscription: {e}")

    async def get_customer_subscriptions(
        self,
        customer_id: str,
        status: str | None = None,
    ) -> list[StripeSubscription]:
        """
        Get all subscriptions for a customer.

        Args:
            customer_id: Stripe customer ID
            status: Filter by status (active, past_due, canceled, etc.)

        Returns:
            List of StripeSubscription
        """
        self._ensure_configured()

        try:
            params = {"customer": customer_id}
            if status:
                params["status"] = status

            subscriptions = stripe.Subscription.list(**params)

            return [self._parse_subscription(s) for s in subscriptions.data]

        except stripe.StripeError as e:
            logger.error(f"Failed to list subscriptions: {e}")
            raise StripeSubscriptionError(f"Failed to list subscriptions: {e}")

    async def update_subscription(
        self,
        subscription_id: str,
        new_price_id: str,
        prorate: bool = True,
    ) -> StripeSubscription:
        """
        Update subscription to a new plan (upgrade/downgrade).

        Args:
            subscription_id: Stripe subscription ID
            new_price_id: New Stripe price ID
            prorate: Whether to prorate the change

        Returns:
            Updated StripeSubscription
        """
        self._ensure_configured()

        try:
            # Get current subscription to find the item to update
            subscription = stripe.Subscription.retrieve(subscription_id)

            if not subscription.items.data:
                raise StripeSubscriptionError("Subscription has no items")

            item_id = subscription.items.data[0].id

            # Update the subscription
            updated = stripe.Subscription.modify(
                subscription_id,
                items=[{"id": item_id, "price": new_price_id}],
                proration_behavior="create_prorations" if prorate else "none",
            )

            logger.info(f"Updated subscription {subscription_id} to price {new_price_id}")

            return self._parse_subscription(updated)

        except stripe.StripeError as e:
            logger.error(f"Failed to update subscription: {e}")
            raise StripeSubscriptionError(f"Failed to update subscription: {e}")

    async def cancel_subscription(
        self,
        subscription_id: str,
        at_period_end: bool = True,
    ) -> StripeSubscription:
        """
        Cancel a subscription.

        Args:
            subscription_id: Stripe subscription ID
            at_period_end: If True, cancel at end of period; if False, immediately

        Returns:
            Updated StripeSubscription
        """
        self._ensure_configured()

        try:
            if at_period_end:
                subscription = stripe.Subscription.modify(
                    subscription_id,
                    cancel_at_period_end=True,
                )
            else:
                subscription = stripe.Subscription.delete(subscription_id)

            logger.info(
                f"Canceled subscription {subscription_id}, "
                f"at_period_end={at_period_end}"
            )

            return self._parse_subscription(subscription)

        except stripe.StripeError as e:
            logger.error(f"Failed to cancel subscription: {e}")
            raise StripeSubscriptionError(f"Failed to cancel subscription: {e}")

    async def resume_subscription(self, subscription_id: str) -> StripeSubscription:
        """
        Resume a subscription that was set to cancel at period end.

        Args:
            subscription_id: Stripe subscription ID

        Returns:
            Updated StripeSubscription
        """
        self._ensure_configured()

        try:
            subscription = stripe.Subscription.modify(
                subscription_id,
                cancel_at_period_end=False,
            )

            logger.info(f"Resumed subscription {subscription_id}")

            return self._parse_subscription(subscription)

        except stripe.StripeError as e:
            logger.error(f"Failed to resume subscription: {e}")
            raise StripeSubscriptionError(f"Failed to resume subscription: {e}")

    # =========================================================================
    # Invoices
    # =========================================================================

    async def get_upcoming_invoice(self, customer_id: str) -> StripeInvoice | None:
        """
        Get upcoming invoice for a customer.

        Args:
            customer_id: Stripe customer ID

        Returns:
            StripeInvoice or None if no upcoming invoice
        """
        self._ensure_configured()

        try:
            invoice = stripe.Invoice.upcoming(customer=customer_id)

            return StripeInvoice(
                id=invoice.id or "upcoming",
                customer_id=customer_id,
                subscription_id=invoice.subscription,
                amount_due=invoice.amount_due,
                amount_paid=invoice.amount_paid,
                status="upcoming",
                created=datetime.fromtimestamp(invoice.created) if invoice.created else datetime.utcnow(),
                due_date=datetime.fromtimestamp(invoice.due_date) if invoice.due_date else None,
                hosted_invoice_url=None,
                pdf_url=None,
            )

        except stripe.InvalidRequestError:
            return None
        except stripe.StripeError as e:
            logger.error(f"Failed to get upcoming invoice: {e}")
            raise StripeSubscriptionError(f"Failed to get upcoming invoice: {e}")

    async def list_invoices(
        self,
        customer_id: str,
        limit: int = 10,
    ) -> list[StripeInvoice]:
        """
        List invoices for a customer.

        Args:
            customer_id: Stripe customer ID
            limit: Maximum number of invoices to return

        Returns:
            List of StripeInvoice
        """
        self._ensure_configured()

        try:
            invoices = stripe.Invoice.list(customer=customer_id, limit=limit)

            return [
                StripeInvoice(
                    id=inv.id,
                    customer_id=inv.customer,
                    subscription_id=inv.subscription,
                    amount_due=inv.amount_due,
                    amount_paid=inv.amount_paid,
                    status=inv.status,
                    created=datetime.fromtimestamp(inv.created),
                    due_date=datetime.fromtimestamp(inv.due_date) if inv.due_date else None,
                    hosted_invoice_url=inv.hosted_invoice_url,
                    pdf_url=inv.invoice_pdf,
                )
                for inv in invoices.data
            ]

        except stripe.StripeError as e:
            logger.error(f"Failed to list invoices: {e}")
            raise StripeSubscriptionError(f"Failed to list invoices: {e}")

    # =========================================================================
    # Billing Portal
    # =========================================================================

    async def create_billing_portal_session(
        self,
        customer_id: str,
        return_url: str,
    ) -> str:
        """
        Create a Stripe Billing Portal session.

        Allows customers to manage their subscription, payment methods,
        and view invoices through Stripe's hosted UI.

        Args:
            customer_id: Stripe customer ID
            return_url: URL to return to after portal session

        Returns:
            Portal session URL
        """
        self._ensure_configured()

        try:
            session = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=return_url,
            )

            logger.info(f"Created billing portal session for customer {customer_id}")

            return session.url

        except stripe.StripeError as e:
            logger.error(f"Failed to create billing portal session: {e}")
            raise StripeSubscriptionError(f"Failed to create billing portal: {e}")

    # =========================================================================
    # Usage Metering
    # =========================================================================

    async def report_usage(
        self,
        subscription_item_id: str,
        quantity: int,
        timestamp: datetime | None = None,
        action: str = "increment",
    ) -> dict[str, Any]:
        """
        Report usage for metered billing.

        Args:
            subscription_item_id: Stripe subscription item ID
            quantity: Usage quantity to report
            timestamp: Time of usage (defaults to now)
            action: "increment" or "set"

        Returns:
            Usage record data
        """
        self._ensure_configured()

        try:
            usage_timestamp = int((timestamp or datetime.utcnow()).timestamp())

            record = stripe.SubscriptionItem.create_usage_record(
                subscription_item_id,
                quantity=quantity,
                timestamp=usage_timestamp,
                action=action,
            )

            logger.info(
                f"Reported usage: {quantity} for item {subscription_item_id}"
            )

            return {
                "id": record.id,
                "quantity": record.quantity,
                "timestamp": datetime.fromtimestamp(record.timestamp),
            }

        except stripe.StripeError as e:
            logger.error(f"Failed to report usage: {e}")
            raise StripeSubscriptionError(f"Failed to report usage: {e}")

    async def get_usage_records(
        self,
        subscription_item_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Get usage records for a subscription item.

        Args:
            subscription_item_id: Stripe subscription item ID
            limit: Maximum records to return

        Returns:
            List of usage records
        """
        self._ensure_configured()

        try:
            records = stripe.SubscriptionItem.list_usage_record_summaries(
                subscription_item_id,
                limit=limit,
            )

            return [
                {
                    "id": r.id,
                    "total_usage": r.total_usage,
                    "period_start": datetime.fromtimestamp(r.period.start),
                    "period_end": datetime.fromtimestamp(r.period.end),
                }
                for r in records.data
            ]

        except stripe.StripeError as e:
            logger.error(f"Failed to get usage records: {e}")
            raise StripeSubscriptionError(f"Failed to get usage records: {e}")

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _parse_subscription(self, subscription) -> StripeSubscription:
        """Parse Stripe subscription object to our dataclass."""
        # Get the plan/price info
        plan_id = ""
        price_id = ""
        items = []

        if subscription.items.data:
            item = subscription.items.data[0]
            price_id = item.price.id
            plan_id = self.get_plan_id_for_price(price_id) or ""
            items = [
                {
                    "id": i.id,
                    "price_id": i.price.id,
                    "quantity": i.quantity,
                }
                for i in subscription.items.data
            ]

        return StripeSubscription(
            id=subscription.id,
            customer_id=subscription.customer,
            status=subscription.status,
            plan_id=plan_id,
            price_id=price_id,
            current_period_start=datetime.fromtimestamp(subscription.current_period_start),
            current_period_end=datetime.fromtimestamp(subscription.current_period_end),
            cancel_at_period_end=subscription.cancel_at_period_end,
            canceled_at=datetime.fromtimestamp(subscription.canceled_at) if subscription.canceled_at else None,
            trial_end=datetime.fromtimestamp(subscription.trial_end) if subscription.trial_end else None,
            items=items,
        )


# Global instance
_stripe_service: StripeService | None = None


def get_stripe_service() -> StripeService:
    """Get or create global Stripe service instance."""
    global _stripe_service
    if _stripe_service is None:
        _stripe_service = StripeService()
    return _stripe_service
