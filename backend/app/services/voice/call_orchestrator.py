"""
Call Orchestrator for managing active voice sessions.

Call flow architecture:
- Manages active call sessions
- Coordinates audio flow: Twilio <-> Backend <-> PersonaPlex
- Handles conversation state
- Sends transcripts to Claude API for intent processing
- Executes tool calls
- Updates call records in MongoDB
- Session cleanup on call end
"""

import asyncio
import base64
import logging
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Awaitable

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.agent import AgentResponse
from app.models.call import Call, CallStatus, CallOutcome, TranscriptEntry
from app.services.call_service import CallService
from app.services.agent_service import AgentService
from app.services.billing.usage_tracker import UsageTracker
from app.services.voice.personaplex_client import (
    PersonaPlexClient,
    PersonaPlexConfig,
    TranscriptEvent,
    AudioEvent,
    PersonaPlexError,
    get_client_pool,
)
from app.services.ai.claude_client import ClaudeClient
from app.services.ai.conversation import ConversationManager, ConversationContext
from app.services.credentials import CredentialResolver
from app.services.ai.tools import register_all_tools
from app.utils.audio import mulaw_to_pcm, pcm_to_mulaw

logger = logging.getLogger(__name__)


class SessionState(str, Enum):
    """Call session states."""

    INITIALIZING = "initializing"
    CONNECTING = "connecting"
    ACTIVE = "active"
    PROCESSING = "processing"  # Processing user input
    SPEAKING = "speaking"
    TRANSFERRING = "transferring"
    ENDING = "ending"
    ENDED = "ended"
    ERROR = "error"


@dataclass
class ConversationTurn:
    """Represents a single conversation turn."""

    speaker: str  # "agent" or "caller"
    text: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    is_final: bool = True


@dataclass
class CallSession:
    """
    Active call session tracking all state and resources.

    Design for multi-tenant, many companies, agents, concurrent calls.
    """

    session_id: str
    call_id: str
    agent: AgentResponse
    company_id: str
    user_id: str
    twilio_call_sid: str

    # Secret handed to Twilio inside the TwiML <Parameter>; the media stream
    # WebSocket must present it in the "start" event before audio is accepted.
    stream_token: str = field(default_factory=lambda: secrets.token_urlsafe(24))

    # State
    state: SessionState = SessionState.INITIALIZING
    started_at: datetime = field(default_factory=datetime.utcnow)
    answered_at: datetime | None = None
    ended_at: datetime | None = None

    # Conversation
    conversation_history: list[ConversationTurn] = field(default_factory=list)
    pending_transcript: str = ""  # Accumulates partial transcripts

    # Audio state
    is_caller_speaking: bool = False
    is_agent_speaking: bool = False
    last_activity_at: datetime = field(default_factory=datetime.utcnow)

    # Metrics
    total_caller_audio_bytes: int = 0
    total_agent_audio_bytes: int = 0
    turn_count: int = 0

    # Resources (set after initialization)
    personaplex_client: PersonaPlexClient | None = None
    conversation_manager: ConversationManager | None = None

    # Caller info (collected during call)
    caller_name: str | None = None
    caller_phone: str | None = None

    # Callbacks for sending audio to Twilio
    _twilio_send_callback: Callable[[bytes], Awaitable[None]] | None = None

    def set_twilio_callback(
        self, callback: Callable[[bytes], Awaitable[None]]
    ) -> None:
        """Set callback for sending audio to Twilio."""
        self._twilio_send_callback = callback

    async def send_to_twilio(self, audio_data: bytes) -> None:
        """Send audio data to Twilio."""
        if self._twilio_send_callback:
            await self._twilio_send_callback(audio_data)
            self.total_agent_audio_bytes += len(audio_data)


class CallOrchestrator:
    """
    Orchestrates voice call sessions.

    Manages the lifecycle of calls and coordinates between:
    - Twilio (telephony)
    - PersonaPlex (voice AI)
    - Claude API (intent processing)
    - MongoDB (call records)

    <200ms turn-taking latency, full-duplex support.
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        """
        Initialize call orchestrator.

        Args:
            db: MongoDB database instance
        """
        self.db = db
        self.call_service = CallService(db)

        # Active sessions (in-memory for now, Redis later)
        self._sessions: dict[str, CallSession] = {}
        self._lock = asyncio.Lock()

        # Cleanup task
        self._cleanup_task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """Start the orchestrator and background tasks."""
        self._running = True

        # Register all Claude tools
        register_all_tools()
        logger.info("Claude tools registered")

        self._cleanup_task = asyncio.create_task(self._session_cleanup_loop())
        logger.info("Call orchestrator started")

    async def stop(self) -> None:
        """Stop the orchestrator and cleanup."""
        self._running = False

        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # End all active sessions
        for session_id in list(self._sessions.keys()):
            await self.end_session(session_id, "orchestrator_shutdown")

        logger.info("Call orchestrator stopped")

    async def create_session(
        self,
        session_id: str,
        call: Call,
        agent: AgentResponse,
        twilio_call_sid: str,
    ) -> CallSession:
        """
        Create a new call session.

        Args:
            session_id: Unique session identifier
            call: Call record from database
            agent: Agent configuration
            twilio_call_sid: Twilio call SID

        Returns:
            Created CallSession
        """
        async with self._lock:
            if session_id in self._sessions:
                logger.warning(f"Session {session_id} already exists")
                return self._sessions[session_id]

            session = CallSession(
                session_id=session_id,
                call_id=call.id,
                agent=agent,
                company_id=call.company_id,
                user_id=call.user_id,
                twilio_call_sid=twilio_call_sid,
            )

            self._sessions[session_id] = session
            logger.info(f"Session created: {session_id} for agent {agent.name}")

            return session

    async def get_session(self, session_id: str) -> CallSession | None:
        """Get a session by ID."""
        return self._sessions.get(session_id)

    async def initialize_session(self, session_id: str) -> None:
        """
        Initialize session by connecting to PersonaPlex.

        Args:
            session_id: Session identifier
        """
        session = self._sessions.get(session_id)
        if not session:
            logger.error(f"Session not found: {session_id}")
            return

        session.state = SessionState.CONNECTING

        try:
            # Build PersonaPlex configuration from agent settings
            config = self._build_personaplex_config(session.agent)

            # Voice server URL: tenant's Settings value, else PERSONAPLEX_URL
            endpoint = await CredentialResolver(self.db).voice_server_url(session.user_id)

            # Get PersonaPlex client
            pool = get_client_pool()
            client = await pool.get_client(
                session_id=session_id,
                config=config,
                on_transcript=lambda evt: self._handle_transcript(session_id, evt),
                on_audio=lambda evt: self._handle_audio(session_id, evt),
                on_error=lambda err: self._handle_personaplex_error(session_id, err),
                endpoint=endpoint,
            )

            session.personaplex_client = client

            # Connect to PersonaPlex
            await client.connect()

            session.state = SessionState.ACTIVE
            session.answered_at = datetime.utcnow()

            # Update call record
            await self.call_service.update_call_status(
                session.call_id,
                CallStatus.IN_PROGRESS,
                answered_at=session.answered_at,
            )

            # Send initial greeting
            await self._send_greeting(session)

            logger.info(f"Session {session_id} initialized and active")

        except Exception as e:
            logger.exception(f"Failed to initialize session {session_id}: {e}")
            session.state = SessionState.ERROR
            await self._handle_session_error(session_id, str(e))

    async def handle_twilio_audio(
        self,
        session_id: str,
        audio_payload: str,
    ) -> None:
        """
        Handle incoming audio from Twilio.

        Audio comes as base64-encoded mulaw at 8kHz.

        Args:
            session_id: Session identifier
            audio_payload: Base64-encoded mulaw audio
        """
        session = self._sessions.get(session_id)
        if not session or session.state not in (
            SessionState.ACTIVE,
            SessionState.PROCESSING,
            SessionState.SPEAKING,
        ):
            return

        session.last_activity_at = datetime.utcnow()
        session.is_caller_speaking = True

        # Decode mulaw audio
        mulaw_audio = base64.b64decode(audio_payload)
        session.total_caller_audio_bytes += len(mulaw_audio)

        # Convert to PCM for PersonaPlex (16-bit, resampled to 24kHz)
        pcm_audio = mulaw_to_pcm(mulaw_audio)

        # Resample from 8kHz to 24kHz (simple linear interpolation)
        pcm_24k = self._resample_8k_to_24k(pcm_audio)

        # Send to PersonaPlex
        if session.personaplex_client and session.personaplex_client.is_connected:
            # If agent is speaking and caller starts talking, handle interruption
            if session.is_agent_speaking:
                await session.personaplex_client.interrupt()
                session.is_agent_speaking = False

            await session.personaplex_client.send_audio(pcm_24k)

    async def handle_twilio_event(
        self,
        session_id: str,
        event_type: str,
        event_data: dict,
    ) -> None:
        """
        Handle Twilio stream events (start, stop, mark, etc.).

        Args:
            session_id: Session identifier
            event_type: Event type
            event_data: Event data
        """
        session = self._sessions.get(session_id)
        if not session:
            return

        if event_type == "start":
            logger.info(f"Twilio stream started for session {session_id}")
            # Stream info is in event_data

        elif event_type == "stop":
            logger.info(f"Twilio stream stopped for session {session_id}")
            await self.end_session(session_id, "stream_stopped")

        elif event_type == "mark":
            # Mark events can be used to track playback completion
            mark_name = event_data.get("name", "")
            logger.debug(f"Twilio mark received: {mark_name}")

    async def _handle_transcript(
        self,
        session_id: str,
        event: TranscriptEvent,
    ) -> None:
        """
        Handle transcript from PersonaPlex STT.

        Args:
            session_id: Session identifier
            event: Transcript event
        """
        session = self._sessions.get(session_id)
        if not session:
            return

        session.is_caller_speaking = not event.is_final

        if event.is_final:
            # Complete utterance - process it
            full_text = (session.pending_transcript + " " + event.text).strip()
            session.pending_transcript = ""

            if full_text:
                # Add to conversation history
                turn = ConversationTurn(
                    speaker="caller",
                    text=full_text,
                    is_final=True,
                )
                session.conversation_history.append(turn)
                session.turn_count += 1

                # Save to call transcript
                await self.call_service.add_transcript_entry(
                    session.call_id,
                    speaker="caller",
                    text=full_text,
                    confidence=event.confidence,
                )

                # Process with Claude (placeholder for Phase 4)
                session.state = SessionState.PROCESSING
                response = await self._process_with_claude(session, full_text)

                # Speak response
                if response and session.personaplex_client:
                    session.state = SessionState.SPEAKING
                    session.is_agent_speaking = True
                    await session.personaplex_client.speak(response)

                    # Add to history
                    agent_turn = ConversationTurn(
                        speaker="agent",
                        text=response,
                        is_final=True,
                    )
                    session.conversation_history.append(agent_turn)

                    # Save to transcript
                    await self.call_service.add_transcript_entry(
                        session.call_id,
                        speaker="agent",
                        text=response,
                    )

                session.state = SessionState.ACTIVE

        else:
            # Partial transcript - accumulate
            session.pending_transcript = event.text

    async def _handle_audio(
        self,
        session_id: str,
        event: AudioEvent,
    ) -> None:
        """
        Handle synthesized audio from PersonaPlex TTS.

        Args:
            session_id: Session identifier
            event: Audio event
        """
        session = self._sessions.get(session_id)
        if not session:
            return

        # Decode audio
        pcm_audio = base64.b64decode(event.audio_base64)

        # Resample from 24kHz to 8kHz for Twilio
        pcm_8k = self._resample_24k_to_8k(pcm_audio)

        # Convert to mulaw for Twilio
        mulaw_audio = pcm_to_mulaw(pcm_8k)

        # Encode and send to Twilio
        await session.send_to_twilio(mulaw_audio)

        if event.is_final:
            session.is_agent_speaking = False

    async def _handle_personaplex_error(
        self,
        session_id: str,
        error: PersonaPlexError,
    ) -> None:
        """Handle PersonaPlex errors."""
        logger.error(f"PersonaPlex error in session {session_id}: {error.message}")

        session = self._sessions.get(session_id)
        if session:
            # Try to reconnect for connection errors
            if error.code == "CONNECTION_ERROR" and session.personaplex_client:
                if await session.personaplex_client.reconnect():
                    logger.info(f"PersonaPlex reconnected for session {session_id}")
                    return

            # Otherwise, end the session
            await self._handle_session_error(session_id, error.message)

    async def _handle_session_error(
        self,
        session_id: str,
        error_message: str,
    ) -> None:
        """Handle session-level errors."""
        session = self._sessions.get(session_id)
        if not session:
            return

        session.state = SessionState.ERROR

        # Log action
        await self.call_service.add_call_action(
            session.call_id,
            action_type="error",
            details={"error": error_message},
            success=False,
            error=error_message,
        )

        # End the session
        await self.end_session(session_id, f"error: {error_message}")

    async def end_session(
        self,
        session_id: str,
        reason: str = "normal",
    ) -> None:
        """
        End a call session and cleanup resources.

        Args:
            session_id: Session identifier
            reason: Reason for ending
        """
        async with self._lock:
            session = self._sessions.pop(session_id, None)

        if not session:
            return

        logger.info(f"Ending session {session_id}: {reason}")
        session.state = SessionState.ENDING
        session.ended_at = datetime.utcnow()

        # Disconnect PersonaPlex
        if session.personaplex_client:
            pool = get_client_pool()
            await pool.remove_client(session_id)

        # Calculate metrics
        duration_seconds = 0
        if session.answered_at and session.ended_at:
            duration_seconds = int(
                (session.ended_at - session.answered_at).total_seconds()
            )

        billable_minutes = duration_seconds / 60.0

        # Determine outcome
        outcome = self._determine_outcome(session)

        # Generate summary
        summary = self._generate_summary(session)

        # Finalize call record
        try:
            await self.call_service.finalize_call(
                session.call_id,
                outcome=outcome,
                summary=summary,
                duration_seconds=duration_seconds,
                billable_minutes=billable_minutes,
            )
        except Exception as e:
            logger.error(f"Failed to finalize call {session.call_id}: {e}")

        # Bill the minutes and roll up per-agent analytics.  Only answered
        # calls count; a call that never connected has no duration.
        if duration_seconds > 0:
            try:
                await UsageTracker(self.db).record_call_usage(
                    user_id=session.user_id,
                    call_id=session.call_id,
                    duration_seconds=duration_seconds,
                    company_id=session.company_id,
                    agent_id=session.agent.id,
                )
            except Exception as e:
                logger.error(f"Failed to record usage for call {session.call_id}: {e}")

        try:
            await AgentService(self.db).update_analytics(
                session.agent.id,
                self._analytics_increment(outcome, duration_seconds),
            )
        except Exception as e:
            logger.error(f"Failed to update analytics for agent {session.agent.id}: {e}")

        session.state = SessionState.ENDED
        logger.info(
            f"Session {session_id} ended. Duration: {duration_seconds}s, "
            f"Turns: {session.turn_count}, Outcome: {outcome.value}"
        )

    def _build_personaplex_config(self, agent: AgentResponse) -> PersonaPlexConfig:
        """Build PersonaPlex configuration from agent settings."""
        # Build system prompt from agent persona
        system_prompt = self._build_system_prompt(agent)

        config = PersonaPlexConfig(
            voice_id=agent.voice.voice_id or "NATF0",
            text_prompt=system_prompt,
            sample_rate=24000,
            speed=agent.voice.speed,
            pitch=agent.voice.pitch,
        )

        # Add voice prompt if available
        if agent.persona.voice_prompt_audio:
            config.voice_prompt_base64 = agent.persona.voice_prompt_audio

        return config

    def _build_system_prompt(self, agent: AgentResponse) -> str:
        """
        Build system prompt for the agent.

        Voice response guidelines:
        - Keep responses SHORT (1-2 sentences)
        - Use conversational language
        - Avoid lists, use natural speech
        - Handle interruptions gracefully
        """
        persona = agent.persona

        prompt_parts = [
            f"You are {persona.display_name}, a {persona.role}.",
            f"Personality: {', '.join(persona.personality)}." if persona.personality else "",
            "",
            "IMPORTANT GUIDELINES:",
            "- Keep responses SHORT (1-2 sentences maximum)",
            "- Use natural, conversational language",
            "- Never use bullet points or lists in speech",
            "- Be helpful and professional",
            "- If interrupted, stop and listen",
            "",
        ]

        if persona.system_prompt:
            prompt_parts.append(persona.system_prompt)

        return "\n".join(prompt_parts)

    async def _send_greeting(self, session: CallSession) -> None:
        """Send initial greeting to caller."""
        greeting = session.agent.persona.greeting

        if not greeting:
            greeting = f"Hello, this is {session.agent.persona.display_name}. How can I help you today?"

        if session.personaplex_client and session.personaplex_client.is_connected:
            session.is_agent_speaking = True
            await session.personaplex_client.speak(greeting)

            # Add to conversation history
            turn = ConversationTurn(speaker="agent", text=greeting)
            session.conversation_history.append(turn)

            # Save to transcript
            await self.call_service.add_transcript_entry(
                session.call_id,
                speaker="agent",
                text=greeting,
            )

    async def _process_with_claude(
        self,
        session: CallSession,
        user_text: str,
    ) -> str:
        """
        Process user input with Claude API using Conversation Manager.

        Uses Haiku 4.5 for low-latency voice responses.

        Args:
            session: Call session
            user_text: User's spoken text

        Returns:
            Agent's response text
        """
        # Initialize conversation manager if not already done
        if session.conversation_manager is None:
            context = ConversationContext(
                session_id=session.session_id,
                call_id=session.call_id,
                agent=session.agent,
                company_id=session.company_id,
                user_id=session.user_id,
                caller_phone=session.caller_phone,
                caller_name=session.caller_name,
            )
            # Claude key: tenant's Settings value, else ANTHROPIC_API_KEY
            api_key = await CredentialResolver(self.db).anthropic_api_key(session.user_id)
            session.conversation_manager = ConversationManager(
                context, claude_client=ClaudeClient(api_key=api_key) if api_key else None
            )

        try:
            # Process input through Claude
            response = await session.conversation_manager.process_user_input(user_text)

            # Handle special actions from tool calls
            if session.conversation_manager.context.collected_info:
                info = session.conversation_manager.context.collected_info

                # Check for transfer action
                if info.get("action") == "transfer":
                    session.state = SessionState.TRANSFERRING
                    # TODO: Trigger actual transfer via Twilio

                # Check for end call action
                if info.get("action") == "end_call":
                    session.state = SessionState.ENDING
                    # End session after response is spoken

                # Update caller info if collected
                if "caller_name" in info:
                    session.caller_name = info["caller_name"]

            return response

        except Exception as e:
            logger.exception(f"Error processing with Claude: {e}")
            # Fallback to simple response on error
            return "I apologize, I'm having a bit of trouble. Could you please repeat that?"

    @staticmethod
    def _analytics_increment(outcome: CallOutcome, duration_seconds: int) -> dict:
        """$inc document for agents.analytics after a call."""
        inc = {
            "analytics.total_calls": 1,
            "analytics.total_minutes": round(duration_seconds / 60.0, 2),
        }
        if outcome == CallOutcome.APPOINTMENT_SCHEDULED:
            inc["analytics.appointments_booked"] = 1
        elif outcome == CallOutcome.MESSAGE_TAKEN:
            inc["analytics.messages_taken"] = 1
        elif outcome == CallOutcome.TRANSFERRED:
            inc["analytics.transfers_made"] = 1
        return inc

    def _determine_outcome(self, session: CallSession) -> CallOutcome:
        """Determine call outcome based on conversation and collected info."""
        # Check collected info from conversation manager first
        if session.conversation_manager:
            info = session.conversation_manager.context.collected_info

            if info.get("appointment_booked"):
                return CallOutcome.APPOINTMENT_SCHEDULED
            if info.get("message_taken"):
                return CallOutcome.MESSAGE_TAKEN
            if info.get("action") == "transfer":
                return CallOutcome.TRANSFERRED
            if info.get("lead_qualified"):
                return CallOutcome.LEAD_QUALIFIED

        # Fallback to analyzing conversation text
        all_text = " ".join(
            turn.text.lower() for turn in session.conversation_history
        )

        if "appointment" in all_text and ("scheduled" in all_text or "booked" in all_text):
            return CallOutcome.APPOINTMENT_SCHEDULED
        elif "message" in all_text and "taken" in all_text:
            return CallOutcome.MESSAGE_TAKEN
        elif "transfer" in all_text:
            return CallOutcome.TRANSFERRED
        elif session.turn_count < 2:
            return CallOutcome.DROPPED
        else:
            return CallOutcome.INFORMATION_PROVIDED

    def _generate_summary(self, session: CallSession) -> str:
        """Generate a brief call summary."""
        # Use conversation manager's summary if available
        if session.conversation_manager:
            return session.conversation_manager.get_conversation_summary()

        if not session.conversation_history:
            return "No conversation recorded."

        # Fallback to basic summary
        turns = session.conversation_history[:6]
        summary_parts = []

        for turn in turns:
            prefix = "Caller" if turn.speaker == "caller" else "Agent"
            text = turn.text[:100] + "..." if len(turn.text) > 100 else turn.text
            summary_parts.append(f"{prefix}: {text}")

        return "\n".join(summary_parts)

    def _resample_8k_to_24k(self, pcm_8k: bytes) -> bytes:
        """
        Resample PCM audio from 8kHz to 24kHz.

        Simple 3x linear interpolation.

        Args:
            pcm_8k: PCM audio at 8kHz (16-bit samples)

        Returns:
            PCM audio at 24kHz
        """
        import struct

        # Unpack 16-bit samples
        samples = struct.unpack(f"<{len(pcm_8k)//2}h", pcm_8k)

        # Upsample 3x with linear interpolation
        resampled = []
        for i in range(len(samples) - 1):
            s1, s2 = samples[i], samples[i + 1]
            resampled.append(s1)
            resampled.append(int(s1 + (s2 - s1) / 3))
            resampled.append(int(s1 + 2 * (s2 - s1) / 3))
        if samples:
            resampled.append(samples[-1])

        # Pack back to bytes
        return struct.pack(f"<{len(resampled)}h", *resampled)

    def _resample_24k_to_8k(self, pcm_24k: bytes) -> bytes:
        """
        Resample PCM audio from 24kHz to 8kHz.

        Simple decimation by 3.

        Args:
            pcm_24k: PCM audio at 24kHz (16-bit samples)

        Returns:
            PCM audio at 8kHz
        """
        import struct

        # Unpack 16-bit samples
        samples = struct.unpack(f"<{len(pcm_24k)//2}h", pcm_24k)

        # Downsample by taking every 3rd sample
        downsampled = samples[::3]

        # Pack back to bytes
        return struct.pack(f"<{len(downsampled)}h", *downsampled)

    async def _session_cleanup_loop(self) -> None:
        """Background task to cleanup stale sessions."""
        while self._running:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds

                now = datetime.utcnow()
                stale_sessions = []

                for session_id, session in self._sessions.items():
                    # Check for sessions inactive for more than 5 minutes
                    inactive_seconds = (now - session.last_activity_at).total_seconds()
                    if inactive_seconds > 300:
                        stale_sessions.append(session_id)

                for session_id in stale_sessions:
                    logger.warning(f"Cleaning up stale session: {session_id}")
                    await self.end_session(session_id, "timeout")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")

    @property
    def active_session_count(self) -> int:
        """Get number of active sessions."""
        return len(self._sessions)


# Global orchestrator instance
_orchestrator: CallOrchestrator | None = None


def get_orchestrator(db: AsyncIOMotorDatabase | None = None) -> CallOrchestrator:
    """
    Get the global call orchestrator instance.

    Args:
        db: Database instance (required on first call)

    Returns:
        CallOrchestrator instance
    """
    global _orchestrator
    if _orchestrator is None:
        if db is None:
            raise RuntimeError("Database required for orchestrator initialization")
        _orchestrator = CallOrchestrator(db)
    return _orchestrator


async def initialize_orchestrator(db: AsyncIOMotorDatabase) -> CallOrchestrator:
    """Initialize and start the global orchestrator."""
    orchestrator = get_orchestrator(db)
    await orchestrator.start()
    return orchestrator


async def shutdown_orchestrator() -> None:
    """Shutdown the global orchestrator."""
    global _orchestrator
    if _orchestrator:
        await _orchestrator.stop()
        _orchestrator = None
