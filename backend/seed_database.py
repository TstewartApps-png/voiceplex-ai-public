"""
Seed the database with a demo user, company and agents.

Goes through the application's own services so the documents are shaped
exactly like the ones the API creates (string foreign keys, hashed passwords,
defaults).  Safe to re-run: existing records are left untouched.

Usage (from backend/, with the same .env the API uses):
    python seed_database.py
"""

from __future__ import annotations

import asyncio

from bson import ObjectId

from app.config import get_settings
from app.database import close_mongodb_connection, connect_to_mongodb, get_database
from app.models.agent import AgentCreate, AgentType, Capabilities, Persona, Voice
from app.models.company import CompanyCreate
from app.models.user import UserCreate
from app.services.agent_service import AgentService
from app.services.auth_service import AuthService, UserAlreadyExistsError
from app.services.company_service import CompanyService
from app.utils.security import hash_password

DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "Test123!"

AGENTS = [
    dict(
        name="Sarah - Receptionist",
        type=AgentType.RECEPTIONIST,
        voice=Voice(voice_id="NATF0", name="Natural Female"),
        persona=Persona(
            display_name="Sarah",
            role="Virtual Receptionist",
            greeting="Thank you for calling Acme Corporation, this is Sarah. How can I help you today?",
            system_prompt="You are Sarah, the friendly receptionist for Acme Corporation. "
            "Answer questions about the business, take messages, and offer to schedule appointments.",
        ),
        capabilities=Capabilities(answer_calls=True, take_messages=True, schedule_appointments=True),
    ),
    dict(
        name="Alex - Scheduler",
        type=AgentType.SCHEDULER,
        voice=Voice(voice_id="NATM0", name="Natural Male"),
        persona=Persona(
            display_name="Alex",
            role="Appointment Scheduler",
            greeting="Hi, this is Alex from Acme. I can help you book or change an appointment.",
            system_prompt="You are Alex, an appointment scheduling assistant. Collect the caller's name, "
            "preferred date and time, and confirm the booking.",
        ),
        capabilities=Capabilities(answer_calls=True, schedule_appointments=True, send_confirmations=True),
    ),
    dict(
        name="Morgan - Lead Qualifier",
        type=AgentType.QUALIFIER,
        voice=Voice(voice_id="PROF0", name="Professional Female"),
        persona=Persona(
            display_name="Morgan",
            role="Sales Assistant",
            greeting="Hello, this is Morgan with Acme. Thanks for your interest - may I ask a few quick questions?",
            system_prompt="You are Morgan, a lead qualification specialist. Ask about the caller's needs, "
            "timeline and budget, and score the lead.",
        ),
        capabilities=Capabilities(answer_calls=True, qualify_leads=True, take_messages=True),
    ),
]


async def seed() -> None:
    settings = get_settings()
    print(f"Seeding {settings.mongodb_db_name} at {settings.mongodb_uri.split('@')[-1]} ...")
    await connect_to_mongodb()
    db = get_database()

    # --- user ------------------------------------------------------------
    auth = AuthService(db)
    try:
        user, _, _ = await auth.register(UserCreate(email=DEMO_EMAIL, name="Test User", password=DEMO_PASSWORD))
        print(f"[OK] created user {DEMO_EMAIL} ({user.id})")
    except UserAlreadyExistsError:
        doc = await db["users"].find_one({"email": DEMO_EMAIL})
        user = await auth.get_user_by_id(str(doc["_id"]))
        # make sure the documented password works even if it was changed
        await db["users"].update_one(
            {"_id": ObjectId(user.id)}, {"$set": {"password_hash": hash_password(DEMO_PASSWORD)}}
        )
        print(f"[OK] user {DEMO_EMAIL} already exists ({user.id}); password reset to documented value")

    # give the demo user a roomier plan so the limits don't get in the way
    await db["users"].update_one(
        {"_id": ObjectId(user.id)},
        {"$set": {"subscription.plan": "growth", "subscription.minutes_included": 2000}},
    )

    # --- company ---------------------------------------------------------
    companies = CompanyService(db)
    existing, _ = await companies.list_companies(user_id=user.id)
    if existing:
        company = existing[0]
        print(f"[OK] company already exists: {company.name} ({company.id})")
    else:
        company = await companies.create_company(
            CompanyCreate(name="Acme Corporation", industry="Technology", website="https://acme-corp.example.com"),
            user_id=user.id,
        )
        print(f"[OK] created company {company.name} ({company.id})")

    # --- agents ----------------------------------------------------------
    agents = AgentService(db)
    existing_agents, _ = await agents.list_agents(user_id=user.id)
    have = {a.name for a in existing_agents}
    for spec in AGENTS:
        if spec["name"] in have:
            print(f"[OK] agent already exists: {spec['name']}")
            continue
        agent = await agents.create_agent(AgentCreate(company_id=company.id, **spec), user_id=user.id)
        if spec["type"] != AgentType.QUALIFIER:
            await agents.activate_agent(agent.id, user_id=user.id)
        print(f"[OK] created agent {agent.name} ({agent.id})")

    await close_mongodb_connection()
    print("\nDone. Log in with", DEMO_EMAIL, "/", DEMO_PASSWORD)


if __name__ == "__main__":
    asyncio.run(seed())
