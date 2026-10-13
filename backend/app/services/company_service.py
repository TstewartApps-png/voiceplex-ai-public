"""
Company service handling company CRUD operations.

Tenant isolation - every query scoped by user_id.
"""

import logging
from datetime import datetime
from typing import Tuple

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.company import (
    Company,
    CompanyCreate,
    CompanyUpdate,
    CompanyResponse,
    PhoneNumber,
    PhoneNumberCreate,
    PhoneNumberStatus,
    PhoneNumberType,
    Integration,
    Branding,
    BusinessHours,
)

logger = logging.getLogger(__name__)


class CompanyServiceError(Exception):
    """Base exception for company service errors."""

    def __init__(self, message: str, code: str):
        self.message = message
        self.code = code
        super().__init__(message)


class CompanyNotFoundError(CompanyServiceError):
    """Raised when company is not found."""

    def __init__(self, company_id: str):
        super().__init__(
            message=f"Company not found: {company_id}",
            code="COMPANY_NOT_FOUND",
        )


class PhoneNumberNotFoundError(CompanyServiceError):
    """Raised when phone number is not found."""

    def __init__(self, number_id: str):
        super().__init__(
            message=f"Phone number not found: {number_id}",
            code="PHONE_NUMBER_NOT_FOUND",
        )


class PhoneNumberInUseError(CompanyServiceError):
    """Raised when phone number is already in use."""

    def __init__(self, number: str):
        super().__init__(
            message=f"Phone number already in use: {number}",
            code="PHONE_NUMBER_IN_USE",
        )


class CompanyService:
    """Service for company operations."""

    def __init__(self, db: AsyncIOMotorDatabase):
        """
        Initialize company service.

        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.collection = db["companies"]

    async def list_companies(
        self,
        user_id: str,
        skip: int = 0,
        limit: int = 50,
    ) -> Tuple[list[CompanyResponse], int]:
        """
        List companies for a user.

        Tenant isolation - every query scoped by user_id.

        Args:
            user_id: Owner user ID
            skip: Number of records to skip
            limit: Maximum records to return

        Returns:
            Tuple of (companies list, total count)
        """
        query = {"user_id": user_id}

        # Get total count
        total = await self.collection.count_documents(query)

        # Get paginated results
        cursor = self.collection.find(query).skip(skip).limit(limit).sort("created_at", -1)
        companies = await cursor.to_list(length=limit)

        return [CompanyResponse.model_validate(c) for c in companies], total

    async def get_company(
        self,
        company_id: str,
        user_id: str,
    ) -> CompanyResponse:
        """
        Get a company by ID.

        Args:
            company_id: Company ID
            user_id: Owner user ID (for access control)

        Returns:
            Company response

        Raises:
            CompanyNotFoundError: If company not found or access denied
        """
        if not ObjectId.is_valid(company_id):
            raise CompanyNotFoundError(company_id)

        company = await self.collection.find_one({
            "_id": ObjectId(company_id),
            "user_id": user_id,
        })

        if not company:
            raise CompanyNotFoundError(company_id)

        return CompanyResponse.model_validate(company)

    async def create_company(
        self,
        company_data: CompanyCreate,
        user_id: str,
    ) -> CompanyResponse:
        """
        Create a new company.

        Args:
            company_data: Company creation data
            user_id: Owner user ID

        Returns:
            Created company response
        """
        now = datetime.utcnow()

        company_doc = {
            "name": company_data.name,
            "industry": company_data.industry,
            "website": company_data.website,
            "user_id": user_id,
            "phone_numbers": [],
            "integrations": Integration().model_dump(),
            "branding": Branding().model_dump(),
            "business_hours": BusinessHours().model_dump(),
            "created_at": now,
            "updated_at": now,
        }

        result = await self.collection.insert_one(company_doc)
        company_doc["_id"] = result.inserted_id

        logger.info(f"Company created: {result.inserted_id} by user {user_id}")

        return CompanyResponse.model_validate(company_doc)

    async def update_company(
        self,
        company_id: str,
        company_data: CompanyUpdate,
        user_id: str,
    ) -> CompanyResponse:
        """
        Update a company.

        Args:
            company_id: Company ID
            company_data: Update data
            user_id: Owner user ID (for access control)

        Returns:
            Updated company response

        Raises:
            CompanyNotFoundError: If company not found or access denied
        """
        if not ObjectId.is_valid(company_id):
            raise CompanyNotFoundError(company_id)

        # Build update document with only provided fields
        update_fields = {"updated_at": datetime.utcnow()}

        if company_data.name is not None:
            update_fields["name"] = company_data.name
        if company_data.industry is not None:
            update_fields["industry"] = company_data.industry
        if company_data.website is not None:
            update_fields["website"] = company_data.website
        if company_data.branding is not None:
            update_fields["branding"] = company_data.branding.model_dump()
        if company_data.business_hours is not None:
            update_fields["business_hours"] = company_data.business_hours.model_dump()

        result = await self.collection.find_one_and_update(
            {"_id": ObjectId(company_id), "user_id": user_id},
            {"$set": update_fields},
            return_document=True,
        )

        if not result:
            raise CompanyNotFoundError(company_id)

        logger.info(f"Company updated: {company_id}")

        return CompanyResponse.model_validate(result)

    async def delete_company(
        self,
        company_id: str,
        user_id: str,
    ) -> bool:
        """
        Delete a company.

        Args:
            company_id: Company ID
            user_id: Owner user ID (for access control)

        Returns:
            True if deleted

        Raises:
            CompanyNotFoundError: If company not found or access denied
        """
        if not ObjectId.is_valid(company_id):
            raise CompanyNotFoundError(company_id)

        result = await self.collection.delete_one({
            "_id": ObjectId(company_id),
            "user_id": user_id,
        })

        if result.deleted_count == 0:
            raise CompanyNotFoundError(company_id)

        # Also delete associated agents and calls
        await self.db["agents"].delete_many({"company_id": company_id})
        await self.db["calls"].delete_many({"company_id": company_id})

        logger.info(f"Company deleted: {company_id}")

        return True

    async def add_phone_number(
        self,
        company_id: str,
        phone_data: PhoneNumberCreate,
        twilio_sid: str,
        user_id: str,
    ) -> CompanyResponse:
        """
        Add a phone number to a company.

        Args:
            company_id: Company ID
            phone_data: Phone number data
            twilio_sid: Twilio phone number SID
            user_id: Owner user ID (for access control)

        Returns:
            Updated company response

        Raises:
            CompanyNotFoundError: If company not found
            PhoneNumberInUseError: If number already assigned
        """
        if not ObjectId.is_valid(company_id):
            raise CompanyNotFoundError(company_id)

        # Check if number is already in use
        existing = await self.collection.find_one({
            "phone_numbers.number": phone_data.number,
        })
        if existing:
            raise PhoneNumberInUseError(phone_data.number)

        phone_number = PhoneNumber(
            _id=str(ObjectId()),
            number=phone_data.number,
            twilio_sid=twilio_sid,
            friendly_name=phone_data.friendly_name,
            agent_id=phone_data.agent_id,
            type=PhoneNumberType.LOCAL,
            status=PhoneNumberStatus.ACTIVE,
        )

        result = await self.collection.find_one_and_update(
            {"_id": ObjectId(company_id), "user_id": user_id},
            {
                "$push": {"phone_numbers": phone_number.model_dump(by_alias=True)},
                "$set": {"updated_at": datetime.utcnow()},
            },
            return_document=True,
        )

        if not result:
            raise CompanyNotFoundError(company_id)

        logger.info(f"Phone number added to company {company_id}: {phone_data.number}")

        return CompanyResponse.model_validate(result)

    async def remove_phone_number(
        self,
        company_id: str,
        number_id: str,
        user_id: str,
    ) -> CompanyResponse:
        """
        Remove a phone number from a company.

        Args:
            company_id: Company ID
            number_id: Phone number ID
            user_id: Owner user ID (for access control)

        Returns:
            Updated company response

        Raises:
            CompanyNotFoundError: If company not found
            PhoneNumberNotFoundError: If phone number not found
        """
        if not ObjectId.is_valid(company_id):
            raise CompanyNotFoundError(company_id)

        # First verify the phone number exists
        company = await self.collection.find_one({
            "_id": ObjectId(company_id),
            "user_id": user_id,
            "phone_numbers._id": number_id,
        })

        if not company:
            # Check if company exists but number doesn't
            exists = await self.collection.find_one({
                "_id": ObjectId(company_id),
                "user_id": user_id,
            })
            if not exists:
                raise CompanyNotFoundError(company_id)
            raise PhoneNumberNotFoundError(number_id)

        result = await self.collection.find_one_and_update(
            {"_id": ObjectId(company_id), "user_id": user_id},
            {
                "$pull": {"phone_numbers": {"_id": number_id}},
                "$set": {"updated_at": datetime.utcnow()},
            },
            return_document=True,
        )

        logger.info(f"Phone number removed from company {company_id}: {number_id}")

        return CompanyResponse.model_validate(result)

    async def assign_agent_to_phone(
        self,
        company_id: str,
        number_id: str,
        agent_id: str | None,
        user_id: str,
    ) -> CompanyResponse:
        """
        Assign or unassign an agent to a phone number.

        Args:
            company_id: Company ID
            number_id: Phone number ID
            agent_id: Agent ID to assign, or None to unassign
            user_id: Owner user ID

        Returns:
            Updated company response
        """
        if not ObjectId.is_valid(company_id):
            raise CompanyNotFoundError(company_id)

        result = await self.collection.find_one_and_update(
            {
                "_id": ObjectId(company_id),
                "user_id": user_id,
                "phone_numbers._id": number_id,
            },
            {
                "$set": {
                    "phone_numbers.$.agent_id": agent_id,
                    "updated_at": datetime.utcnow(),
                },
            },
            return_document=True,
        )

        if not result:
            raise PhoneNumberNotFoundError(number_id)

        logger.info(f"Agent {agent_id} assigned to phone {number_id}")

        return CompanyResponse.model_validate(result)

    async def count_companies(self, user_id: str) -> int:
        """
        Count companies for a user.

        Args:
            user_id: Owner user ID

        Returns:
            Number of companies
        """
        return await self.collection.count_documents({"user_id": user_id})

    async def get_company_by_phone(self, phone_number: str) -> CompanyResponse | None:
        """
        Get company by phone number.

        Used for inbound call routing.

        Args:
            phone_number: Phone number in E.164 format

        Returns:
            Company if found, None otherwise
        """
        company = await self.collection.find_one({
            "phone_numbers.number": phone_number,
            "phone_numbers.status": PhoneNumberStatus.ACTIVE.value,
        })

        if not company:
            return None

        return CompanyResponse.model_validate(company)
