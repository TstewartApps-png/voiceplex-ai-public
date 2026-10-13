"""
Subscription-related model definitions.

Supplements user subscription model with plan details and pricing.
"""

from pydantic import BaseModel, Field


class PlanLimits(BaseModel):
    """Limits for a subscription plan."""

    agents: int = Field(..., description="Max number of agents")
    companies: int = Field(..., description="Max number of companies")
    minutes_per_month: int = Field(..., description="Minutes included per month")
    knowledge_items: int = Field(..., description="Max knowledge base items per agent")
    team_members: int = Field(..., description="Max team members (for agency)")


class PlanDetails(BaseModel):
    """Complete plan information."""

    id: str = Field(..., description="Plan identifier")
    name: str = Field(..., description="Plan display name")
    description: str = Field(..., description="Plan description")
    price_monthly_cents: int = Field(..., description="Monthly price in cents")
    price_yearly_cents: int = Field(..., description="Yearly price in cents")
    limits: PlanLimits = Field(..., description="Plan limits")
    features: list[str] = Field(..., description="Plan features list")


# Plan configurations
PLAN_FREE = PlanDetails(
    id="free",
    name="Free",
    description="Get started with basic features",
    price_monthly_cents=0,
    price_yearly_cents=0,
    limits=PlanLimits(
        agents=1,
        companies=1,
        minutes_per_month=50,
        knowledge_items=10,
        team_members=1,
    ),
    features=[
        "1 AI Agent",
        "50 minutes/month",
        "Basic analytics",
        "Email support",
    ],
)

PLAN_STARTER = PlanDetails(
    id="starter",
    name="Starter",
    description="Perfect for small businesses",
    price_monthly_cents=4900,
    price_yearly_cents=47000,
    limits=PlanLimits(
        agents=2,
        companies=1,
        minutes_per_month=500,
        knowledge_items=50,
        team_members=1,
    ),
    features=[
        "2 AI Agents",
        "500 minutes/month",
        "Calendar integration",
        "Call recordings",
        "Basic analytics",
        "Email support",
    ],
)

PLAN_GROWTH = PlanDetails(
    id="growth",
    name="Growth",
    description="For growing businesses",
    price_monthly_cents=9900,
    price_yearly_cents=95000,
    limits=PlanLimits(
        agents=5,
        companies=3,
        minutes_per_month=2000,
        knowledge_items=200,
        team_members=3,
    ),
    features=[
        "5 AI Agents",
        "2,000 minutes/month",
        "3 companies",
        "Google & Microsoft Calendar",
        "Gmail integration",
        "Advanced analytics",
        "Priority support",
    ],
)

PLAN_PROFESSIONAL = PlanDetails(
    id="professional",
    name="Professional",
    description="For established businesses",
    price_monthly_cents=19900,
    price_yearly_cents=191000,
    limits=PlanLimits(
        agents=15,
        companies=10,
        minutes_per_month=5000,
        knowledge_items=500,
        team_members=10,
    ),
    features=[
        "15 AI Agents",
        "5,000 minutes/month",
        "10 companies",
        "All integrations",
        "Custom voice cloning",
        "API access",
        "Dedicated support",
    ],
)

PLAN_AGENCY = PlanDetails(
    id="agency",
    name="Agency",
    description="For agencies managing multiple clients",
    price_monthly_cents=49900,
    price_yearly_cents=479000,
    limits=PlanLimits(
        agents=50,
        companies=50,
        minutes_per_month=20000,
        knowledge_items=2000,
        team_members=50,
    ),
    features=[
        "50 AI Agents",
        "20,000 minutes/month",
        "50 companies",
        "White-label options",
        "Client management",
        "Bulk operations",
        "Dedicated account manager",
    ],
)

# Plan lookup dictionary
PLANS: dict[str, PlanDetails] = {
    "free": PLAN_FREE,
    "starter": PLAN_STARTER,
    "growth": PLAN_GROWTH,
    "professional": PLAN_PROFESSIONAL,
    "agency": PLAN_AGENCY,
}


def get_plan_limits(plan_id: str) -> PlanLimits:
    """
    Get limits for a plan.

    Args:
        plan_id: Plan identifier

    Returns:
        PlanLimits for the plan, defaults to free if not found
    """
    plan = PLANS.get(plan_id, PLAN_FREE)
    return plan.limits


def get_plan_details(plan_id: str) -> PlanDetails:
    """
    Get complete plan details.

    Args:
        plan_id: Plan identifier

    Returns:
        PlanDetails for the plan, defaults to free if not found
    """
    return PLANS.get(plan_id, PLAN_FREE)


def get_plan_order() -> list[str]:
    """
    Get plans in order from lowest to highest tier.

    Returns:
        List of plan IDs in tier order
    """
    return ["free", "starter", "growth", "professional", "agency"]


def is_upgrade(current_plan: str, new_plan: str) -> bool:
    """
    Check if changing from current_plan to new_plan is an upgrade.

    Args:
        current_plan: Current plan ID
        new_plan: New plan ID

    Returns:
        True if new_plan is higher tier than current_plan
    """
    order = get_plan_order()
    current_idx = order.index(current_plan) if current_plan in order else 0
    new_idx = order.index(new_plan) if new_plan in order else 0
    return new_idx > current_idx


def is_downgrade(current_plan: str, new_plan: str) -> bool:
    """
    Check if changing from current_plan to new_plan is a downgrade.

    Args:
        current_plan: Current plan ID
        new_plan: New plan ID

    Returns:
        True if new_plan is lower tier than current_plan
    """
    order = get_plan_order()
    current_idx = order.index(current_plan) if current_plan in order else 0
    new_idx = order.index(new_plan) if new_plan in order else 0
    return new_idx < current_idx


def get_plan_price_env_key(plan_id: str) -> str | None:
    """
    Get the environment variable key for a plan's Stripe price ID.

    Args:
        plan_id: Plan identifier

    Returns:
        Environment variable key or None if free plan
    """
    if plan_id == "free":
        return None
    return f"STRIPE_PRICE_{plan_id.upper()}"
