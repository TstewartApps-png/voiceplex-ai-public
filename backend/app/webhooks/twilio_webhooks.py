"""
Twilio webhook endpoints for handling call events.

Webhooks:
- POST /api/v1/webhooks/twilio/voice - Incoming call handler
- POST /api/v1/webhooks/twilio/voice/status - Call status updates
- POST /api/v1/webhooks/twilio/voice/recording - Recording ready callback

Webhook signature verification for security.
"""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, HTTPException, status, Form, Query
from fastapi.responses import Response

from app.database import get_database
from app.services.agent_service import AgentService
from app.services.company_service import CompanyService
from app.services.call_service import CallService
from app.services.voice.twilio_handler import (
    get_twilio_handler,
    TwilioHandler,
    TwilioCallInfo,
)
from app.services.credentials import CredentialResolver
from app.services.voice.call_orchestrator import get_orchestrator
from app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/twilio", tags=["Twilio Webhooks"])


async def verify_twilio_webhook(request: Request) -> None:
    """
    FastAPI dependency: verify the X-Twilio-Signature of a webhook request.

    Twilio signs  <full public URL incl. query string> + <sorted POST params>
    with the account auth token.  We reconstruct the URL from BACKEND_URL (the
    URL Twilio was configured with) and also accept the raw / X-Forwarded-*
    variants so ngrok/reverse proxies work.

    Reading request.form() here is safe: Starlette caches it, so the endpoints'
    Form() parameters still resolve.
    """
    settings = get_settings()
    signature = request.headers.get("X-Twilio-Signature")

    if not signature:
        if settings.debug:
            logger.warning("Twilio signature missing - allowed because DEBUG=true")
            return
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"detail": "Missing Twilio signature", "code": "MISSING_SIGNATURE"},
        )

    form = await request.form()
    params = {k: v for k, v in form.items() if isinstance(v, str)}

    # Which auth token signed this?  The tenant that owns the number / call,
    # looked up from the payload itself, plus the platform token as fallback.
    tokens = await CredentialResolver(get_database()).twilio_auth_tokens_for_webhook(
        called_number=params.get("To"), call_sid=params.get("CallSid")
    )
    if not tokens:
        if settings.debug:
            logger.warning("No Twilio auth token available - signature not validated (DEBUG=true)")
            return
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"detail": "Twilio is not configured", "code": "TWILIO_NOT_CONFIGURED"},
        )

    for token in tokens:
        for url in _candidate_urls(request, settings.backend_url):
            if TwilioHandler.signature_is_valid(token, url, params, signature):
                return

    logger.warning("Invalid Twilio signature for %s", request.url.path)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"detail": "Invalid Twilio signature", "code": "INVALID_SIGNATURE"},
    )


def _candidate_urls(request: Request, backend_url: str) -> list[str]:
    """URLs Twilio may have signed for this request (configured base, forwarded, raw)."""
    path_qs = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    candidates: list[str] = []
    if backend_url:
        candidates.append(backend_url.rstrip("/") + path_qs)
    proto = request.headers.get("x-forwarded-proto")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if proto and host:
        candidates.append(f"{proto}://{host}{path_qs}")
    candidates.append(str(request.url))
    # de-duplicate, keep order
    return list(dict.fromkeys(candidates))


_twilio_signed = [Depends(verify_twilio_webhook)]


@router.post(
    "/voice",
    dependencies=_twilio_signed,
    response_class=Response,
    summary="Incoming voice call webhook",
    description="Handle incoming voice calls from Twilio.",
)
async def handle_incoming_call(
    request: Request,
    # Twilio POST parameters
    CallSid: Annotated[str, Form()] = "",
    AccountSid: Annotated[str, Form()] = "",
    From: Annotated[str, Form()] = "",
    To: Annotated[str, Form()] = "",
    CallStatus: Annotated[str, Form()] = "",
    Direction: Annotated[str, Form()] = "inbound",
    CallerName: Annotated[str | None, Form()] = None,
    FromCity: Annotated[str | None, Form()] = None,
    FromState: Annotated[str | None, Form()] = None,
    FromCountry: Annotated[str | None, Form()] = None,
) -> Response:
    """
    Handle incoming voice calls.

    This is called by Twilio when a call comes in to one of our numbers.

    Flow:
    1. Verify request signature
    2. Look up agent assigned to the called number
    3. Create call record in database
    4. Return TwiML to start MediaStream

    Returns:
        TwiML response
    """
    logger.info(f"Incoming call: {CallSid} from {From} to {To}")

    # Build call info
    call_info = TwilioCallInfo(
        call_sid=CallSid,
        account_sid=AccountSid,
        from_number=From,
        to_number=To,
        direction=TwilioCallInfo.from_webhook_params({
            "Direction": Direction,
            "CallStatus": CallStatus,
        }).direction,
        status=TwilioCallInfo.from_webhook_params({
            "CallStatus": CallStatus,
        }).status,
        caller_name=CallerName,
        caller_city=FromCity,
        caller_state=FromState,
        caller_country=FromCountry,
    )

    handler = get_twilio_handler()
    db = get_database()

    # Look up agent for this phone number
    agent_service = AgentService(db)
    company_service = CompanyService(db)

    agent = await agent_service.get_agent_by_phone(To)

    if not agent:
        logger.warning(f"No agent found for number {To}")
        # Return TwiML that says "Sorry" and hangs up
        twiml = handler.generate_hangup_twiml(
            "Sorry, this number is not currently in service. Please try again later."
        )
        return Response(content=twiml, media_type="application/xml")

    # Get company for the agent
    company = await company_service.get_company(agent.company_id, agent.user_id)

    # Create call record
    call_service = CallService(db)
    call = await call_service.create_inbound_call(
        agent_id=agent.id,
        company_id=agent.company_id,
        user_id=agent.user_id,
        from_number=From,
        to_number=To,
        twilio_call_sid=CallSid,
    )

    # Generate unique session ID
    session_id = f"call_{uuid.uuid4().hex[:16]}"

    # Create session in orchestrator
    orchestrator = get_orchestrator(db)
    session = await orchestrator.create_session(
        session_id=session_id,
        call=call,
        agent=agent,
        twilio_call_sid=CallSid,
    )

    # Generate greeting from company branding or agent persona
    greeting = None
    if company.branding.company_greeting:
        greeting = f"{company.branding.company_greeting}. Please wait while I connect you with {agent.persona.display_name}."

    # Generate TwiML to start media stream
    twiml = handler.generate_answer_twiml(
        session_id=session_id,
        greeting=greeting,
        stream_token=session.stream_token,
    )

    logger.info(f"Call {CallSid} connected to agent {agent.name} (session: {session_id})")

    return Response(content=twiml, media_type="application/xml")


@router.post(
    "/voice/outbound",
    dependencies=_twilio_signed,
    response_class=Response,
    summary="Outbound call TwiML",
    description="Return TwiML for outbound calls.",
)
async def handle_outbound_call(
    request: Request,
    session_id: Annotated[str, Query()],
    CallSid: Annotated[str, Form()] = "",
) -> Response:
    """
    Handle outbound call connection.

    Called by Twilio when an outbound call is answered.
    Returns TwiML to start MediaStream.
    """
    logger.info(f"Outbound call answered: {CallSid} (session: {session_id})")

    handler = get_twilio_handler()
    session = await get_orchestrator(get_database()).get_session(session_id)
    if not session:
        return Response(
            content=handler.generate_hangup_twiml("Sorry, this call could not be connected."),
            media_type="application/xml",
        )

    # Generate TwiML for media stream
    twiml = handler.generate_outbound_twiml(
        session_id=session_id, stream_token=session.stream_token
    )

    return Response(content=twiml, media_type="application/xml")


@router.post(
    "/voice/status",
    dependencies=_twilio_signed,
    summary="Call status webhook",
    description="Handle call status updates from Twilio.",
)
async def handle_call_status(
    request: Request,
    CallSid: Annotated[str, Form()] = "",
    CallStatus: Annotated[str, Form()] = "",
    CallDuration: Annotated[int | None, Form()] = None,
    Timestamp: Annotated[str | None, Form()] = None,
) -> dict:
    """
    Handle call status updates.

    Twilio sends status updates for:
    - initiated: Call has been created
    - ringing: Call is ringing
    - answered: Call was answered
    - completed: Call ended

    Args:
        CallSid: Twilio call SID
        CallStatus: New status
        CallDuration: Call duration in seconds (on completion)
    """
    logger.info(f"Call status update: {CallSid} -> {CallStatus}")

    db = get_database()
    call_service = CallService(db)

    # Find call by Twilio SID
    call = await call_service.get_call_by_twilio_sid(CallSid)

    if not call:
        logger.warning(f"Call not found for status update: {CallSid}")
        return {"status": "ignored", "reason": "call_not_found"}

    # Map Twilio status to our status
    from app.models.call import CallStatus as OurCallStatus

    status_map = {
        "initiated": OurCallStatus.QUEUED,
        "queued": OurCallStatus.QUEUED,
        "ringing": OurCallStatus.RINGING,
        "in-progress": OurCallStatus.IN_PROGRESS,
        "completed": OurCallStatus.COMPLETED,
        "busy": OurCallStatus.BUSY,
        "no-answer": OurCallStatus.NO_ANSWER,
        "canceled": OurCallStatus.FAILED,
        "failed": OurCallStatus.FAILED,
    }

    new_status = status_map.get(CallStatus.lower())

    if new_status:
        update_fields = {}
        if CallDuration is not None:
            update_fields["duration_seconds"] = CallDuration

        await call_service.update_call_status(
            call.id,
            new_status,
            **update_fields,
        )

    # If completed, end the orchestrator session
    if CallStatus.lower() == "completed":
        orchestrator = get_orchestrator(db)
        # Find session by call ID
        for session_id, session in list(orchestrator._sessions.items()):
            if session.twilio_call_sid == CallSid:
                await orchestrator.end_session(session_id, "call_completed")
                break

    return {"status": "processed", "call_status": CallStatus}


@router.post(
    "/voice/recording",
    dependencies=_twilio_signed,
    summary="Recording ready webhook",
    description="Handle recording ready callback from Twilio.",
)
async def handle_recording_ready(
    request: Request,
    CallSid: Annotated[str, Form()] = "",
    RecordingSid: Annotated[str, Form()] = "",
    RecordingUrl: Annotated[str, Form()] = "",
    RecordingDuration: Annotated[int | None, Form()] = None,
    RecordingStatus: Annotated[str, Form()] = "",
) -> dict:
    """
    Handle recording ready callback.

    Twilio sends this when a call recording is available.
    """
    logger.info(f"Recording ready: {RecordingSid} for call {CallSid}")

    if RecordingStatus != "completed":
        return {"status": "ignored", "reason": f"recording_status_{RecordingStatus}"}

    db = get_database()
    call_service = CallService(db)

    # Find call by Twilio SID
    call = await call_service.get_call_by_twilio_sid(CallSid)

    if not call:
        logger.warning(f"Call not found for recording: {CallSid}")
        return {"status": "ignored", "reason": "call_not_found"}

    # Update call with recording info
    # Add .mp3 extension to URL for playback
    recording_url = f"{RecordingUrl}.mp3"

    from bson import ObjectId
    await db["calls"].update_one(
        {"_id": ObjectId(call.id)},
        {
            "$set": {
                "twilio_recording_sid": RecordingSid,
                "recording_url": recording_url,
                "recording_duration": RecordingDuration,
            }
        },
    )

    logger.info(f"Recording saved for call {call.id}: {recording_url}")

    return {"status": "processed", "recording_sid": RecordingSid}


@router.post(
    "/voice/transfer-status",
    dependencies=_twilio_signed,
    response_class=Response,
    summary="Transfer status webhook",
    description="Handle transfer completion status.",
)
async def handle_transfer_status(
    request: Request,
    DialCallStatus: Annotated[str, Form()] = "",
) -> Response:
    """
    Handle transfer completion.

    Called after a transferred call ends.
    """
    logger.info(f"Transfer status: {DialCallStatus}")

    handler = get_twilio_handler()

    if DialCallStatus in ("busy", "no-answer", "failed", "canceled"):
        # Transfer failed, apologize and hang up
        twiml = handler.generate_hangup_twiml(
            "I'm sorry, I wasn't able to connect you. Please try calling again later."
        )
    else:
        # Transfer completed, just hang up
        twiml = handler.generate_hangup_twiml()

    return Response(content=twiml, media_type="application/xml")


@router.post(
    "/voice/whisper",
    dependencies=_twilio_signed,
    response_class=Response,
    summary="Whisper message for transfers",
    description="Play whisper message to transfer recipient.",
)
async def handle_whisper(
    request: Request,
    message: Annotated[str, Query()] = "",
) -> Response:
    """
    Play whisper message to transfer recipient before connecting.
    """
    from twilio.twiml.voice_response import VoiceResponse

    response = VoiceResponse()
    if message:
        response.say(message, voice="Polly.Joanna")

    return Response(content=str(response), media_type="application/xml")
