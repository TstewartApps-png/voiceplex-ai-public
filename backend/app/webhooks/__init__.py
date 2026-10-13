"""
Webhook handlers for external service integrations.

Webhooks:
- Twilio: Voice call events, status updates, recordings
- Stripe: Subscription events, payment updates
"""

from app.webhooks.twilio_webhooks import router as twilio_webhooks_router
from app.webhooks.stripe_webhooks import router as stripe_webhooks_router

__all__ = ["twilio_webhooks_router", "stripe_webhooks_router"]
