"""
MongoDB database connection and utilities.

MongoDB Atlas is the primary data store.
Indexes on: user.email, company.user_id, agent.company_id,
call.agent_id, call.company_id, call.created_at
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import IndexModel, ASCENDING, DESCENDING
from pymongo.errors import CollectionInvalid

from app.config import get_settings

logger = logging.getLogger(__name__)

# Global database client and database instances
_client: AsyncIOMotorClient | None = None
_database: AsyncIOMotorDatabase | None = None


async def connect_to_mongodb() -> None:
    """
    Establish connection to MongoDB.

    Creates the global client and database instances.
    Should be called during application startup.
    """
    global _client, _database

    settings = get_settings()

    logger.info("Connecting to MongoDB...")

    _client = AsyncIOMotorClient(
        settings.mongodb_uri,
        maxPoolSize=50,
        minPoolSize=10,
        maxIdleTimeMS=30000,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
    )

    _database = _client[settings.mongodb_db_name]

    # Verify connection
    await _client.admin.command("ping")
    logger.info(f"Connected to MongoDB database: {settings.mongodb_db_name}")

    # Create indexes
    await create_indexes()


async def close_mongodb_connection() -> None:
    """
    Close MongoDB connection.

    Should be called during application shutdown.
    """
    global _client, _database

    if _client is not None:
        logger.info("Closing MongoDB connection...")
        _client.close()
        _client = None
        _database = None
        logger.info("MongoDB connection closed")


def get_database() -> AsyncIOMotorDatabase:
    """
    Get the database instance.

    Raises:
        RuntimeError: If database is not connected.

    Returns:
        The MongoDB database instance.
    """
    if _database is None:
        raise RuntimeError("Database not connected. Call connect_to_mongodb() first.")
    return _database


async def create_indexes() -> None:
    """
    Create database indexes for optimal query performance.

    Indexes:
    - user.email (unique)
    - company.user_id
    - agent.company_id
    - call.agent_id, call.company_id, call.created_at
    """
    db = get_database()

    # Users collection indexes
    users_indexes = [
        IndexModel([("email", ASCENDING)], unique=True, name="email_unique"),
        IndexModel([("created_at", DESCENDING)], name="created_at_desc"),
    ]
    await _create_collection_indexes(db, "users", users_indexes)

    # Companies collection indexes
    companies_indexes = [
        IndexModel([("user_id", ASCENDING)], name="user_id"),
        IndexModel([("created_at", DESCENDING)], name="created_at_desc"),
    ]
    await _create_collection_indexes(db, "companies", companies_indexes)

    # Agents collection indexes
    agents_indexes = [
        IndexModel([("company_id", ASCENDING)], name="company_id"),
        IndexModel([("user_id", ASCENDING)], name="user_id"),
        IndexModel([("status", ASCENDING)], name="status"),
        IndexModel(
            [("company_id", ASCENDING), ("status", ASCENDING)],
            name="company_id_status",
        ),
        IndexModel([("created_at", DESCENDING)], name="created_at_desc"),
    ]
    await _create_collection_indexes(db, "agents", agents_indexes)

    # Calls collection indexes
    calls_indexes = [
        IndexModel([("agent_id", ASCENDING)], name="agent_id"),
        IndexModel([("company_id", ASCENDING)], name="company_id"),
        IndexModel([("user_id", ASCENDING)], name="user_id"),
        IndexModel([("created_at", DESCENDING)], name="created_at_desc"),
        IndexModel([("twilio_call_sid", ASCENDING)], unique=True, sparse=True, name="twilio_call_sid"),
        IndexModel(
            [("company_id", ASCENDING), ("created_at", DESCENDING)],
            name="company_id_created_at",
        ),
        IndexModel(
            [("agent_id", ASCENDING), ("created_at", DESCENDING)],
            name="agent_id_created_at",
        ),
        IndexModel([("status", ASCENDING)], name="status"),
    ]
    await _create_collection_indexes(db, "calls", calls_indexes)

    # Sessions collection indexes (for refresh tokens)
    sessions_indexes = [
        IndexModel([("user_id", ASCENDING)], name="user_id"),
        IndexModel([("refresh_token", ASCENDING)], unique=True, name="refresh_token"),
        IndexModel([("expires_at", ASCENDING)], expireAfterSeconds=0, name="expires_at_ttl"),
    ]
    await _create_collection_indexes(db, "sessions", sessions_indexes)

    # Usage records collection indexes (for billing)
    usage_indexes = [
        IndexModel([("user_id", ASCENDING)], name="user_id"),
        IndexModel([("call_id", ASCENDING)], unique=True, sparse=True, name="call_id"),
        IndexModel([("recorded_at", DESCENDING)], name="recorded_at_desc"),
        IndexModel(
            [("user_id", ASCENDING), ("recorded_at", DESCENDING)],
            name="user_id_recorded_at",
        ),
        IndexModel([("company_id", ASCENDING)], name="company_id"),
        IndexModel([("agent_id", ASCENDING)], name="agent_id"),
    ]
    await _create_collection_indexes(db, "usage_records", usage_indexes)

    # Settings collection indexes (for integration configurations)
    settings_indexes = [
        IndexModel([("user_id", ASCENDING)], unique=True, name="user_id_unique"),
    ]
    await _create_collection_indexes(db, "settings", settings_indexes)

    logger.info("Database indexes created successfully")


async def _create_collection_indexes(
    db: AsyncIOMotorDatabase,
    collection_name: str,
    indexes: list[IndexModel],
) -> None:
    """
    Create indexes for a collection.

    Args:
        db: Database instance
        collection_name: Name of the collection
        indexes: List of IndexModel instances to create
    """
    try:
        collection = db[collection_name]
        await collection.create_indexes(indexes)
        logger.debug(f"Created indexes for collection: {collection_name}")
    except Exception as e:
        logger.error(f"Error creating indexes for {collection_name}: {e}")
        raise


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncIOMotorDatabase, None]:
    """
    Context manager for database sessions.

    Provides a database instance for use in async with blocks.
    Useful for dependency injection patterns.

    Yields:
        The MongoDB database instance.
    """
    db = get_database()
    try:
        yield db
    finally:
        # Motor handles connection pooling automatically
        pass
