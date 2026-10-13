"""
API v1 router aggregating all endpoint routers.

All API endpoints are under /api/v1/
"""

from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.companies import router as companies_router
from app.api.v1.agents import router as agents_router
from app.api.v1.calls import router as calls_router
from app.api.v1.voice import router as voice_router
from app.api.v1.integrations import router as integrations_router
from app.api.v1.billing import router as billing_router
from app.api.v1.settings import router as settings_router
from app.api.v1.knowledge import router as knowledge_router
from app.webhooks.twilio_webhooks import router as twilio_webhooks_router
from app.webhooks.stripe_webhooks import router as stripe_webhooks_router

# These will be added in subsequent phases:
# from app.api.v1.users import router as users_router

router = APIRouter(prefix="/api/v1")

# Include all routers
router.include_router(auth_router)

# Phase 2: Core API
router.include_router(companies_router)
router.include_router(agents_router)
router.include_router(calls_router)

# Phase 3: Voice Integration
router.include_router(voice_router)
router.include_router(twilio_webhooks_router)

# Phase 5: OAuth integrations
router.include_router(integrations_router)

# Phase 6: Stripe billing
router.include_router(billing_router)
router.include_router(stripe_webhooks_router)

# Settings & integrations configuration
router.include_router(settings_router)

# Knowledge base management
router.include_router(knowledge_router)
