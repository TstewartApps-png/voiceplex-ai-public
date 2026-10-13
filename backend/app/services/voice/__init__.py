"""
Voice services for VoicePlex AI.

Voice layer:
- PersonaPlex WebSocket client for full-duplex voice AI
- Twilio handler for telephony operations
- Call orchestrator for session management
"""

from app.services.voice.personaplex_client import (
    PersonaPlexClient,
    PersonaPlexConfig,
    PersonaPlexClientPool,
    TranscriptEvent,
    AudioEvent,
    PersonaPlexError,
    ConnectionError,
    ConfigurationError,
    get_client_pool,
)
from app.services.voice.twilio_handler import (
    TwilioHandler,
    TwilioCallInfo,
    TwilioHandlerError,
    InvalidSignatureError,
    get_twilio_handler,
)
from app.services.voice.call_orchestrator import (
    CallOrchestrator,
    CallSession,
    SessionState,
    get_orchestrator,
    initialize_orchestrator,
    shutdown_orchestrator,
)

__all__ = [
    # PersonaPlex
    "PersonaPlexClient",
    "PersonaPlexConfig",
    "PersonaPlexClientPool",
    "TranscriptEvent",
    "AudioEvent",
    "PersonaPlexError",
    "ConnectionError",
    "ConfigurationError",
    "get_client_pool",
    # Twilio
    "TwilioHandler",
    "TwilioCallInfo",
    "TwilioHandlerError",
    "InvalidSignatureError",
    "get_twilio_handler",
    # Orchestrator
    "CallOrchestrator",
    "CallSession",
    "SessionState",
    "get_orchestrator",
    "initialize_orchestrator",
    "shutdown_orchestrator",
]
