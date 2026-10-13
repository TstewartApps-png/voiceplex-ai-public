"""
Companies API endpoints.

API endpoints:
- GET    /api/v1/companies
- POST   /api/v1/companies
- GET    /api/v1/companies/{id}
- PUT    /api/v1/companies/{id}
- DELETE /api/v1/companies/{id}
- POST   /api/v1/companies/{id}/phone-numbers
- DELETE /api/v1/companies/{id}/phone-numbers/{number_id}
"""

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, status, Query
from pydantic import BaseModel, Field

from app.services.voice.twilio_handler import TwilioHandler, TwilioHandlerError
from app.api.deps import (
    CurrentUser,
    Database,
    check_subscription_limit,
    verify_agent_access,
    verify_company_access,
)
from app.models.company import (
    CompanyCreate,
    CompanyUpdate,
    CompanyResponse,
    PhoneNumberCreate,
)
from app.services.company_service import (
    CompanyService,
    CompanyNotFoundError,
    PhoneNumberNotFoundError,
    PhoneNumberInUseError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/companies", tags=["Companies"])


# Response models
class CompanyListResponse(BaseModel):
    """Paginated company list response."""

    items: list[CompanyResponse] = Field(..., description="List of companies")
    total: int = Field(..., description="Total number of companies")
    skip: int = Field(..., description="Number skipped")
    limit: int = Field(..., description="Maximum returned")


class MessageResponse(BaseModel):
    """Simple message response."""

    message: str = Field(..., description="Response message")


class ProvisionPhoneRequest(BaseModel):
    """Attach an existing Twilio number (from the tenant's account) to a company."""

    number: str = Field(
        ...,
        description="Phone number in E.164 format, already owned in your Twilio account",
        pattern=r"^\+[1-9]\d{6,14}$",
        examples=["+14155552671"],
    )
    friendly_name: str = Field(
        default="", description="Human-readable name for the number"
    )
    agent_id: str | None = Field(
        default=None, description="Agent to assign to this number"
    )


def _get_company_service(db: Database) -> CompanyService:
    """Get company service instance."""
    return CompanyService(db)


@router.get(
    "",
    response_model=CompanyListResponse,
    summary="List companies",
    description="Get all companies for the current user with pagination.",
)
async def list_companies(
    current_user: CurrentUser,
    db: Database,
    skip: Annotated[int, Query(ge=0, description="Records to skip")] = 0,
    limit: Annotated[int, Query(ge=1, le=100, description="Max records")] = 50,
) -> CompanyListResponse:
    """
    List companies for the current user.

    - Supports pagination with skip/limit
    - Results sorted by creation date (newest first)
    """
    service = _get_company_service(db)
    companies, total = await service.list_companies(
        user_id=current_user.id,
        skip=skip,
        limit=limit,
    )

    return CompanyListResponse(
        items=companies,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post(
    "",
    response_model=CompanyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create company",
    description="Create a new company for the current user.",
)
async def create_company(
    company_data: CompanyCreate,
    current_user: CurrentUser,
    db: Database,
) -> CompanyResponse:
    """
    Create a new company.

    - Checks subscription limit for companies
    - Creates with default settings for integrations, branding, business hours
    """
    service = _get_company_service(db)

    # Check subscription limit
    current_count = await service.count_companies(current_user.id)
    check_subscription_limit(current_user, "companies", current_count)

    company = await service.create_company(
        company_data=company_data,
        user_id=current_user.id,
    )

    logger.info(f"Company created: {company.id} for user {current_user.id}")

    return company


@router.get(
    "/{company_id}",
    response_model=CompanyResponse,
    summary="Get company",
    description="Get a specific company by ID.",
)
async def get_company(
    company_id: str,
    current_user: CurrentUser,
    db: Database,
) -> CompanyResponse:
    """
    Get company details.

    - Returns 404 if company not found or user doesn't have access
    """
    service = _get_company_service(db)

    try:
        company = await service.get_company(
            company_id=company_id,
            user_id=current_user.id,
        )
        return company
    except CompanyNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": e.message, "code": e.code},
        )


@router.put(
    "/{company_id}",
    response_model=CompanyResponse,
    summary="Update company",
    description="Update a company's settings.",
)
async def update_company(
    company_id: str,
    company_data: CompanyUpdate,
    current_user: CurrentUser,
    db: Database,
) -> CompanyResponse:
    """
    Update company details.

    - Only updates provided fields
    - Can update name, industry, website, branding, business hours
    """
    service = _get_company_service(db)

    try:
        company = await service.update_company(
            company_id=company_id,
            company_data=company_data,
            user_id=current_user.id,
        )

        logger.info(f"Company updated: {company_id}")

        return company
    except CompanyNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": e.message, "code": e.code},
        )


@router.delete(
    "/{company_id}",
    response_model=MessageResponse,
    summary="Delete company",
    description="Delete a company and all associated data.",
)
async def delete_company(
    company_id: str,
    current_user: CurrentUser,
    db: Database,
) -> MessageResponse:
    """
    Delete a company.

    - Also deletes all associated agents and calls
    - Phone numbers should be released via Twilio first
    """
    service = _get_company_service(db)

    try:
        await service.delete_company(
            company_id=company_id,
            user_id=current_user.id,
        )

        logger.info(f"Company deleted: {company_id}")

        return MessageResponse(message="Company deleted successfully")
    except CompanyNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": e.message, "code": e.code},
        )


@router.post(
    "/{company_id}/phone-numbers",
    response_model=CompanyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Attach Twilio phone number",
    description="Attach a number from your Twilio account to the company and route it to an agent.",
)
async def add_phone_number(
    company_id: str,
    phone_data: ProvisionPhoneRequest,
    current_user: CurrentUser,
    db: Database,
) -> CompanyResponse:
    """
    Attach a Twilio phone number to a company and route its calls to an agent.

    1. Verifies the number exists in the tenant's Twilio account (Settings > Twilio)
    2. Points the number's voice + status webhooks at this backend
    3. Stores the number (with its real Twilio SID) on the company

    Buying numbers is intentionally not done here; buy them in the Twilio
    console (or extend this endpoint with ``TwilioHandler.purchase_phone_number``).
    """
    service = _get_company_service(db)
    await verify_company_access(company_id, current_user, db)

    if phone_data.agent_id:
        agent = await verify_agent_access(phone_data.agent_id, current_user, db)
        if agent.get("company_id") != company_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"detail": "Agent belongs to a different company", "code": "AGENT_COMPANY_MISMATCH"},
            )

    handler = await TwilioHandler.for_user(db, current_user.id)
    if not handler.is_configured:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "detail": "Twilio is not configured. Save and test your credentials under Settings > Twilio first.",
                "code": "TWILIO_NOT_CONFIGURED",
            },
        )

    try:
        found = await handler.lookup_phone_number(phone_data.number)
        if not found:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "detail": f"{phone_data.number} is not a number in your Twilio account",
                    "code": "TWILIO_NUMBER_NOT_FOUND",
                },
            )
        await handler.configure_phone_number(found["sid"], friendly_name=phone_data.friendly_name or None)
    except TwilioHandlerError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"detail": e.message, "code": e.code},
        )

    try:
        company = await service.add_phone_number(
            company_id=company_id,
            phone_data=PhoneNumberCreate(
                number=found["phone_number"],
                friendly_name=phone_data.friendly_name or found.get("friendly_name") or "",
                agent_id=phone_data.agent_id,
            ),
            twilio_sid=found["sid"],
            user_id=current_user.id,
        )

        logger.info(f"Phone number attached to company {company_id}: {found['phone_number']} ({found['sid']})")

        return company
    except CompanyNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": e.message, "code": e.code},
        )
    except PhoneNumberInUseError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"detail": e.message, "code": e.code},
        )


@router.delete(
    "/{company_id}/phone-numbers/{number_id}",
    response_model=CompanyResponse,
    summary="Remove phone number",
    description="Release a phone number from the company.",
)
async def remove_phone_number(
    company_id: str,
    number_id: str,
    current_user: CurrentUser,
    db: Database,
) -> CompanyResponse:
    """
    Remove a phone number from a company.

    In production, this would:
    1. Release the number back to Twilio
    2. Remove webhook configuration
    3. Remove from the company

    For now, just removes from the company record.
    """
    service = _get_company_service(db)

    # TODO: Integrate with Twilio to release number

    try:
        company = await service.remove_phone_number(
            company_id=company_id,
            number_id=number_id,
            user_id=current_user.id,
        )

        logger.info(f"Phone number removed from company {company_id}: {number_id}")

        return company
    except CompanyNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": e.message, "code": e.code},
        )
    except PhoneNumberNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": e.message, "code": e.code},
        )
