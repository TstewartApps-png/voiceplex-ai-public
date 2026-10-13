"""
Voice API endpoints including WebSocket for Twilio media streams.

Call flow:
- Twilio opens WebSocket for bidirectional audio
- Backend connects to PersonaPlex WebSocket
- Audio flows: Twilio <-> Backend <-> PersonaPlex
"""

import asyncio
import base64
import json
import logging
from typing import Annotated

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, HTTPException, status, Depends
from starlette.websockets import WebSocketState
from pydantic import BaseModel, Field
import websockets

from app.database import get_database
from app.services.voice.call_orchestrator import get_orchestrator
from app.api.deps import CurrentUser, Database

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voice", tags=["Voice"])


# ─── Available NVIDIA PersonaPlex Voice Catalog ────────────────────────────
AVAILABLE_VOICES = [
    {"id": "NATF0", "name": "Natural Female", "gender": "female", "style": "natural", "description": "Warm, conversational female voice — great for receptionists"},
    {"id": "NATM0", "name": "Natural Male", "gender": "male", "style": "natural", "description": "Warm, conversational male voice — great for receptionists"},
    {"id": "NATF1", "name": "Natural Female Alt", "gender": "female", "style": "natural", "description": "Friendly, upbeat female voice — ideal for schedulers"},
    {"id": "NATM1", "name": "Natural Male Alt", "gender": "male", "style": "natural", "description": "Friendly, upbeat male voice — ideal for schedulers"},
    {"id": "PROF0", "name": "Professional Female", "gender": "female", "style": "professional", "description": "Polished, authoritative female voice — suited for lead qualification"},
    {"id": "PROM0", "name": "Professional Male", "gender": "male", "style": "professional", "description": "Polished, authoritative male voice — suited for lead qualification"},
    {"id": "PROF1", "name": "Professional Female Alt", "gender": "female", "style": "professional", "description": "Crisp, precise female voice — ideal for corporate settings"},
    {"id": "PROM1", "name": "Professional Male Alt", "gender": "male", "style": "professional", "description": "Crisp, precise male voice — ideal for corporate settings"},
    {"id": "CALM0", "name": "Calm Female", "gender": "female", "style": "calm", "description": "Soothing, patient female voice — best for appointment reminders"},
    {"id": "CALM1", "name": "Calm Male", "gender": "male", "style": "calm", "description": "Soothing, patient male voice — best for appointment reminders"},
    {"id": "ENRG0", "name": "Energetic Female", "gender": "female", "style": "energetic", "description": "Bright, enthusiastic female voice — great for outbound calls"},
    {"id": "ENRG1", "name": "Energetic Male", "gender": "male", "style": "energetic", "description": "Bright, enthusiastic male voice — great for outbound calls"},
]


@router.get("/voices", summary="List available PersonaPlex voices")
async def list_voices(current_user: CurrentUser) -> dict:
    """Return the catalog of available NVIDIA PersonaPlex voices."""
    return {"voices": AVAILABLE_VOICES}


# Voice Preview Models
class VoicePreviewRequest(BaseModel):
    """Request for voice preview generation."""
    voice_id: str = Field(..., description="PersonaPlex voice ID (e.g., NATF0, NATM1)")
    text: str = Field(..., min_length=1, max_length=500, description="Text to synthesize")
    speed: float = Field(default=1.0, ge=0.5, le=2.0, description="Speech speed multiplier")
    stability: float = Field(default=0.5, ge=0.0, le=1.0, description="Voice stability")
    style: float = Field(default=0.5, ge=0.0, le=1.0, description="Style exaggeration")


class VoicePreviewResponse(BaseModel):
    """Response containing generated audio."""
    audio_base64: str = Field(..., description="Base64-encoded audio data")
    sample_rate: int = Field(default=24000, description="Audio sample rate in Hz")
    duration_ms: int = Field(default=0, description="Audio duration in milliseconds")


@router.post("/preview", response_model=VoicePreviewResponse)
async def generate_voice_preview(
    request: VoicePreviewRequest,
    current_user: CurrentUser,
    db: Database,
) -> VoicePreviewResponse:
    """
    Generate a voice preview audio clip using PersonaPlex TTS.

    Requires PersonaPlex to be configured in user settings.
    """
    # Get PersonaPlex URL from user settings
    settings = await db["settings"].find_one({"user_id": current_user.id})

    if not settings or not settings.get("personaplex"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"detail": "PersonaPlex not configured. Go to Settings to configure.", "code": "PERSONAPLEX_NOT_CONFIGURED"},
        )

    personaplex_settings = settings["personaplex"]
    if not personaplex_settings.get("connected") or not personaplex_settings.get("websocket_url"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"detail": "PersonaPlex not connected. Test your connection in Settings.", "code": "PERSONAPLEX_NOT_CONNECTED"},
        )

    websocket_url = personaplex_settings["websocket_url"]

    # Connect to PersonaPlex and request TTS
    try:
        audio_data = await _generate_tts_audio(
            websocket_url=websocket_url,
            voice_id=request.voice_id,
            text=request.text,
            speed=request.speed,
        )

        return VoicePreviewResponse(
            audio_base64=audio_data["audio"],
            sample_rate=audio_data.get("sample_rate", 24000),
            duration_ms=audio_data.get("duration_ms", 0),
        )

    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={"detail": "PersonaPlex request timed out", "code": "PERSONAPLEX_TIMEOUT"},
        )
    except Exception as e:
        logger.error(f"Voice preview failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"detail": f"PersonaPlex error: {str(e)}", "code": "PERSONAPLEX_ERROR"},
        )


def _pcm_to_wav(pcm_base64: str, sample_rate: int = 24000) -> str:
    """
    Convert raw PCM audio to WAV format with proper headers.

    Args:
        pcm_base64: Base64-encoded PCM audio data (16-bit, mono)
        sample_rate: Audio sample rate in Hz

    Returns:
        Base64-encoded WAV audio data
    """
    import struct

    pcm_data = base64.b64decode(pcm_base64)

    # WAV header parameters
    num_channels = 1
    bits_per_sample = 16
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = len(pcm_data)

    # Build WAV header (44 bytes)
    wav_header = struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF',
        36 + data_size,  # File size - 8
        b'WAVE',
        b'fmt ',
        16,              # PCM format chunk size
        1,               # Audio format (1 = PCM)
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b'data',
        data_size
    )

    wav_data = wav_header + pcm_data
    return base64.b64encode(wav_data).decode('utf-8')


async def _generate_tts_audio(
    websocket_url: str,
    voice_id: str,
    text: str,
    speed: float = 1.0,
    timeout: float = 120.0,  # Increased to 120s for PersonaPlex model loading
) -> dict:
    """
    Connect to PersonaPlex and generate TTS audio.

    Uses the correct PersonaPlex protocol:
    1. Send config message with voice settings
    2. Wait for config_ack
    3. Send speak request with text
    4. Receive audio response

    Args:
        websocket_url: PersonaPlex WebSocket URL
        voice_id: Voice ID to use
        text: Text to synthesize
        speed: Speech speed multiplier
        timeout: Request timeout in seconds

    Returns:
        Dictionary with audio_base64 (WAV format), sample_rate, duration_ms
    """
    sample_rate = 24000

    async with websockets.connect(
        websocket_url,
        ping_interval=30,
        ping_timeout=60,  # Increased for long TTS operations
        close_timeout=10,
    ) as ws:
        # Step 1: Send configuration
        config_msg = {
            "type": "config",
            "voice_id": voice_id,
            "sample_rate": sample_rate,
            "speed": speed,
            "language": "en",
        }
        await ws.send(json.dumps(config_msg))
        logger.debug(f"Sent config: {config_msg}")

        # Step 2: Wait for config acknowledgment
        try:
            response = await asyncio.wait_for(ws.recv(), timeout=5)
            data = json.loads(response)

            if data.get("type") == "error":
                raise Exception(data.get("message", "PersonaPlex config error"))

            # Accept config_ack, ready, or ack as valid responses
            if data.get("type") not in ("config_ack", "ready", "ack"):
                logger.warning(f"Unexpected config response: {data.get('type')}")

        except asyncio.TimeoutError:
            logger.warning("Config ack timeout, proceeding anyway")

        # Step 3: Send TTS request (matches PersonaPlex server protocol)
        tts_msg = {"type": "tts", "text": text, "voice_id": voice_id, "speed": speed}
        await ws.send(json.dumps(tts_msg))
        logger.debug(f"Sent TTS request: {text[:50]}...")

        # Step 4: Wait for audio response (may receive ack first)
        start_time = asyncio.get_event_loop().time()
        while True:
            remaining = timeout - (asyncio.get_event_loop().time() - start_time)
            if remaining <= 0:
                raise asyncio.TimeoutError("Timeout waiting for audio")

            try:
                response = await asyncio.wait_for(ws.recv(), timeout=remaining)
                data = json.loads(response)

                if data.get("type") == "audio":
                    # Get PCM audio data (might be in 'data' or 'audio' field)
                    pcm_base64 = data.get("data") or data.get("audio", "")

                    if not pcm_base64:
                        raise Exception("No audio data in response")

                    # Convert PCM to WAV for browser playback
                    wav_base64 = _pcm_to_wav(pcm_base64, sample_rate)

                    return {
                        "audio": wav_base64,
                        "sample_rate": sample_rate,
                        "duration_ms": data.get("duration_ms", 0),
                    }

                elif data.get("type") == "error":
                    raise Exception(data.get("message", "PersonaPlex returned an error"))

                elif data.get("type") in ("ack", "ready", "connected", "pong"):
                    # Server status message - continue waiting for audio
                    logger.debug(f"Received {data.get('type')}, waiting for audio...")
                    continue

                else:
                    logger.warning(f"Unexpected response type: {data.get('type')}, continuing...")
                    # Don't raise exception, just continue waiting
                    continue

            except asyncio.TimeoutError:
                raise

    # Should not reach here
    return {"audio": "", "sample_rate": sample_rate, "duration_ms": 0}


@router.websocket("/stream/{session_id}")
async def twilio_media_stream(
    websocket: WebSocket,
    session_id: str,
):
    """
    WebSocket endpoint for Twilio media streams.

    Twilio sends/receives audio as JSON messages with base64-encoded mulaw.

    Message types from Twilio:
    - connected: WebSocket connected
    - start: Stream started (contains stream SID, call SID)
    - media: Audio payload (base64 mulaw)
    - stop: Stream ended
    - mark: Playback marker

    Message types to Twilio:
    - media: Audio payload to play
    - mark: Request playback marker
    - clear: Clear audio queue
    """
    await websocket.accept()
    logger.info(f"Twilio WebSocket connected for session {session_id}")

    db = get_database()
    orchestrator = get_orchestrator(db)

    session = await orchestrator.get_session(session_id)
    if not session:
        logger.error(f"Session not found: {session_id}")
        await websocket.close(code=1008, reason="Session not found")
        return

    # Set up callback for sending audio to Twilio
    stream_sid: str | None = None

    async def send_audio_to_twilio(audio_data: bytes) -> None:
        """Send audio data to Twilio via WebSocket."""
        nonlocal stream_sid
        if websocket.client_state != WebSocketState.CONNECTED:
            return

        if not stream_sid:
            logger.warning("Cannot send audio: stream SID not set")
            return

        # Encode audio to base64
        audio_base64 = base64.b64encode(audio_data).decode("utf-8")

        message = {
            "event": "media",
            "streamSid": stream_sid,
            "media": {
                "payload": audio_base64,
            },
        }

        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Failed to send audio to Twilio: {e}")

    session.set_twilio_callback(send_audio_to_twilio)

    try:
        while True:
            # Receive message from Twilio
            data = await websocket.receive_text()
            message = json.loads(data)
            event_type = message.get("event")

            if event_type == "connected":
                # WebSocket connected
                logger.debug(f"Twilio stream connected: {message.get('protocol')}")

            elif event_type == "start":
                # Stream started - extract metadata
                start_info = message.get("start", {})
                stream_sid = start_info.get("streamSid")
                call_sid = start_info.get("callSid")
                custom_params = start_info.get("customParameters", {})

                logger.info(
                    f"Twilio stream started: streamSid={stream_sid}, "
                    f"callSid={call_sid}"
                )

                # The TwiML we handed Twilio carries a per-session secret; refuse
                # any stream that does not present it (prevents audio hijack by
                # anyone who learns a session id).
                if custom_params.get("token") != session.stream_token:
                    logger.warning(f"Stream token mismatch for session {session_id}; closing")
                    await websocket.close(code=1008, reason="Invalid stream token")
                    return

                # Initialize the PersonaPlex connection
                await orchestrator.initialize_session(session_id)

                # Notify orchestrator
                await orchestrator.handle_twilio_event(
                    session_id,
                    "start",
                    {
                        "stream_sid": stream_sid,
                        "call_sid": call_sid,
                        "custom_params": custom_params,
                    },
                )

            elif event_type == "media":
                # Audio from caller
                media_info = message.get("media", {})
                payload = media_info.get("payload", "")
                track = media_info.get("track", "inbound")

                if track == "inbound" and payload:
                    # Send to orchestrator for processing
                    await orchestrator.handle_twilio_audio(session_id, payload)

            elif event_type == "stop":
                # Stream ended
                logger.info(f"Twilio stream stopped for session {session_id}")
                await orchestrator.handle_twilio_event(session_id, "stop", {})
                break

            elif event_type == "mark":
                # Playback marker
                mark_info = message.get("mark", {})
                await orchestrator.handle_twilio_event(
                    session_id,
                    "mark",
                    {"name": mark_info.get("name")},
                )

            else:
                logger.debug(f"Unknown Twilio event: {event_type}")

    except WebSocketDisconnect:
        logger.info(f"Twilio WebSocket disconnected for session {session_id}")

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON from Twilio: {e}")

    except Exception as e:
        logger.exception(f"Error in Twilio WebSocket handler: {e}")

    finally:
        # Clean up session
        await orchestrator.end_session(session_id, "websocket_closed")
        logger.info(f"Twilio WebSocket handler finished for session {session_id}")


@router.get(
    "/sessions",
    summary="List active voice sessions",
    description="Get information about active voice sessions (admin endpoint).",
)
async def list_active_sessions(current_user: CurrentUser) -> dict:
    """
    List the caller's active voice sessions.

    Sessions are tenant-scoped: only sessions owned by the authenticated user
    are returned.  Session ids are not sufficient to attach to the media
    stream (a separate stream token is required), but we still avoid leaking
    other tenants' activity.
    """
    db = get_database()
    orchestrator = get_orchestrator(db)

    sessions = []
    for session_id, session in orchestrator._sessions.items():
        if session.user_id != current_user.id:
            continue
        sessions.append({
            "session_id": session_id,
            "call_id": session.call_id,
            "agent_name": session.agent.name,
            "state": session.state.value,
            "turn_count": session.turn_count,
            "started_at": session.started_at.isoformat(),
            "is_caller_speaking": session.is_caller_speaking,
            "is_agent_speaking": session.is_agent_speaking,
        })

    return {
        "active_sessions": len(sessions),
        "sessions": sessions,
    }


@router.get(
    "/sessions/{session_id}",
    summary="Get session details",
    description="Get detailed information about a specific voice session.",
)
async def get_session_details(session_id: str, current_user: CurrentUser) -> dict:
    """
    Get details of one of the caller's voice sessions (transcript included).
    """
    db = get_database()
    orchestrator = get_orchestrator(db)

    session = await orchestrator.get_session(session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": "Session not found", "code": "SESSION_NOT_FOUND"},
        )

    # Build conversation history for response
    conversation = [
        {
            "speaker": turn.speaker,
            "text": turn.text,
            "timestamp": turn.timestamp.isoformat(),
        }
        for turn in session.conversation_history
    ]

    return {
        "session_id": session_id,
        "call_id": session.call_id,
        "agent": {
            "id": session.agent.id,
            "name": session.agent.name,
            "type": session.agent.type.value,
        },
        "state": session.state.value,
        "started_at": session.started_at.isoformat(),
        "answered_at": session.answered_at.isoformat() if session.answered_at else None,
        "turn_count": session.turn_count,
        "conversation": conversation,
        "metrics": {
            "caller_audio_bytes": session.total_caller_audio_bytes,
            "agent_audio_bytes": session.total_agent_audio_bytes,
        },
    }


@router.post(
    "/sessions/{session_id}/end",
    summary="End a voice session",
    description="Manually end an active voice session.",
)
async def end_session(session_id: str, current_user: CurrentUser) -> dict:
    """
    Manually end one of the caller's voice sessions.
    """
    db = get_database()
    orchestrator = get_orchestrator(db)

    session = await orchestrator.get_session(session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"detail": "Session not found", "code": "SESSION_NOT_FOUND"},
        )

    await orchestrator.end_session(session_id, "manual_termination")

    return {"status": "ended", "session_id": session_id}
