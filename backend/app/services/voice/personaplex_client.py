"""
PersonaPlex WebSocket client for full-duplex voice AI.

NVIDIA PersonaPlex-7B-v1 provides full-duplex voice AI
with <200ms latency and natural interruptions.

Connection flow:
1. Connect to PersonaPlex WebSocket endpoint
2. Send configuration (voice_prompt, text_prompt, voice_id, sample_rate)
3. Stream audio bidirectionally
4. Receive transcripts and synthesized audio
"""

import asyncio
import base64
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import AsyncGenerator, Callable, Awaitable

import websockets
from websockets.client import WebSocketClientProtocol
from websockets.exceptions import (
    ConnectionClosed,
    ConnectionClosedError,
    ConnectionClosedOK,
)

from app.config import get_settings

logger = logging.getLogger(__name__)


class PersonaPlexMessageType(str, Enum):
    """Message types for PersonaPlex communication."""

    # Outgoing (to PersonaPlex)
    CONFIG = "config"
    AUDIO = "audio"
    SPEAK = "speak"
    INTERRUPT = "interrupt"
    END = "end"

    # Incoming (from PersonaPlex)
    READY = "ready"
    TRANSCRIPT = "transcript"
    AUDIO_RESPONSE = "audio"
    SPEAKING = "speaking"
    STOPPED = "stopped"
    ERROR = "error"


class ConnectionState(str, Enum):
    """WebSocket connection states."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    CONFIGURED = "configured"
    ERROR = "error"


@dataclass
class PersonaPlexConfig:
    """Configuration for PersonaPlex voice session."""

    voice_id: str = "NATF0"
    voice_prompt_base64: str | None = None  # 3-10s audio for voice cloning
    text_prompt: str = ""  # System prompt for persona
    sample_rate: int = 24000
    language: str = "en"

    # Voice parameters
    speed: float = 1.0
    pitch: float = 1.0

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        config = {
            "type": PersonaPlexMessageType.CONFIG.value,
            "voice_id": self.voice_id,
            "text_prompt": self.text_prompt,
            "sample_rate": self.sample_rate,
            "language": self.language,
            "speed": self.speed,
            "pitch": self.pitch,
        }
        if self.voice_prompt_base64:
            config["voice_prompt"] = self.voice_prompt_base64
        return config


@dataclass
class TranscriptEvent:
    """Transcript event from PersonaPlex STT."""

    text: str
    is_final: bool
    confidence: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    speaker: str = "caller"


@dataclass
class AudioEvent:
    """Audio event from PersonaPlex TTS."""

    audio_base64: str
    sample_rate: int
    duration_ms: int
    is_final: bool


class PersonaPlexError(Exception):
    """Base exception for PersonaPlex errors."""

    def __init__(self, message: str, code: str = "PERSONAPLEX_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class ConnectionError(PersonaPlexError):
    """Connection-related errors."""

    def __init__(self, message: str):
        super().__init__(message, "CONNECTION_ERROR")


class ConfigurationError(PersonaPlexError):
    """Configuration-related errors."""

    def __init__(self, message: str):
        super().__init__(message, "CONFIGURATION_ERROR")


# Type aliases for callbacks
TranscriptCallback = Callable[[TranscriptEvent], Awaitable[None]]
AudioCallback = Callable[[AudioEvent], Awaitable[None]]
ErrorCallback = Callable[[PersonaPlexError], Awaitable[None]]


class PersonaPlexClient:
    """
    WebSocket client for PersonaPlex voice AI.

    Manages bidirectional audio streaming and transcript handling.
    """

    def __init__(
        self,
        session_id: str,
        config: PersonaPlexConfig,
        on_transcript: TranscriptCallback | None = None,
        on_audio: AudioCallback | None = None,
        on_error: ErrorCallback | None = None,
        endpoint: str | None = None,
    ):
        """
        Initialize PersonaPlex client.

        Args:
            session_id: Unique session identifier for logging
            config: PersonaPlex configuration
            on_transcript: Callback for transcript events
            on_audio: Callback for audio events
            on_error: Callback for error events
            endpoint: Voice server WebSocket URL (resolved per tenant by the
                orchestrator; falls back to PERSONAPLEX_URL from the environment)
        """
        self.session_id = session_id
        self.config = config
        self.on_transcript = on_transcript
        self.on_audio = on_audio
        self.on_error = on_error

        self._ws: WebSocketClientProtocol | None = None
        self._state = ConnectionState.DISCONNECTED
        self._receive_task: asyncio.Task | None = None
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 3
        self._reconnect_delay = 1.0

        self._is_speaking = False
        self._pending_audio_queue: asyncio.Queue[bytes] = asyncio.Queue()

        self._endpoint = endpoint or get_settings().personaplex_url

    @property
    def state(self) -> ConnectionState:
        """Get current connection state."""
        return self._state

    @property
    def is_connected(self) -> bool:
        """Check if connected and configured."""
        return self._state == ConnectionState.CONFIGURED

    @property
    def is_speaking(self) -> bool:
        """Check if PersonaPlex is currently speaking."""
        return self._is_speaking

    async def connect(self) -> None:
        """
        Establish WebSocket connection to PersonaPlex.

        Raises:
            ConnectionError: If connection fails
        """
        if self._state in (ConnectionState.CONNECTING, ConnectionState.CONFIGURED):
            logger.warning(f"[{self.session_id}] Already connected or connecting")
            return

        if not self._endpoint:
            self._state = ConnectionState.ERROR
            raise ConfigurationError(
                "Voice server URL not configured (Settings > Voice server, or PERSONAPLEX_URL)"
            )

        self._state = ConnectionState.CONNECTING
        logger.info(f"[{self.session_id}] Connecting to PersonaPlex: {self._endpoint}")

        try:
            self._ws = await websockets.connect(
                self._endpoint,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5,
                max_size=10 * 1024 * 1024,  # 10MB for audio
            )

            self._state = ConnectionState.CONNECTED
            logger.info(f"[{self.session_id}] WebSocket connected")

            # Start receive loop
            self._receive_task = asyncio.create_task(self._receive_loop())

            # Send configuration
            await self._send_config()

        except Exception as e:
            self._state = ConnectionState.ERROR
            logger.error(f"[{self.session_id}] Connection failed: {e}")
            raise ConnectionError(f"Failed to connect to PersonaPlex: {e}")

    async def disconnect(self) -> None:
        """Gracefully disconnect from PersonaPlex."""
        if self._ws is None:
            return

        logger.info(f"[{self.session_id}] Disconnecting from PersonaPlex")

        # Cancel receive task
        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass

        # Send end message
        try:
            await self._send_message({"type": PersonaPlexMessageType.END.value})
        except Exception:
            pass

        # Close WebSocket
        try:
            await self._ws.close()
        except Exception:
            pass

        self._ws = None
        self._state = ConnectionState.DISCONNECTED
        logger.info(f"[{self.session_id}] Disconnected")

    async def send_audio(self, audio_data: bytes) -> None:
        """
        Send audio data to PersonaPlex for STT processing.

        Args:
            audio_data: PCM audio bytes (24kHz, 16-bit, mono)
        """
        if not self.is_connected:
            logger.warning(f"[{self.session_id}] Cannot send audio: not connected")
            return

        # Encode audio to base64
        audio_base64 = base64.b64encode(audio_data).decode("utf-8")

        await self._send_message({
            "type": PersonaPlexMessageType.AUDIO.value,
            "audio": audio_base64,
        })

    async def speak(self, text: str) -> None:
        """
        Request PersonaPlex to speak text via TTS.

        Args:
            text: Text to synthesize and speak
        """
        if not self.is_connected:
            logger.warning(f"[{self.session_id}] Cannot speak: not connected")
            return

        logger.debug(f"[{self.session_id}] Speaking: {text[:50]}...")

        await self._send_message({
            "type": PersonaPlexMessageType.SPEAK.value,
            "text": text,
        })

    async def interrupt(self) -> None:
        """
        Interrupt current speech (barge-in support).

        Call this when the user starts speaking while the agent is talking.
        """
        if not self.is_connected:
            return

        logger.debug(f"[{self.session_id}] Interrupting speech")

        await self._send_message({
            "type": PersonaPlexMessageType.INTERRUPT.value,
        })

        self._is_speaking = False

    async def _send_config(self) -> None:
        """Send configuration to PersonaPlex."""
        logger.info(f"[{self.session_id}] Sending configuration")

        config_message = self.config.to_dict()
        await self._send_message(config_message)

    async def _send_message(self, message: dict) -> None:
        """
        Send JSON message to PersonaPlex.

        Args:
            message: Message dictionary to send
        """
        if self._ws is None:
            raise ConnectionError("Not connected")

        try:
            await self._ws.send(json.dumps(message))
        except ConnectionClosed as e:
            logger.error(f"[{self.session_id}] Connection closed while sending: {e}")
            self._state = ConnectionState.ERROR
            raise ConnectionError(f"Connection closed: {e}")

    async def _receive_loop(self) -> None:
        """Main loop for receiving messages from PersonaPlex."""
        if self._ws is None:
            return

        logger.debug(f"[{self.session_id}] Starting receive loop")

        try:
            async for message in self._ws:
                await self._handle_message(message)

        except ConnectionClosedOK:
            logger.info(f"[{self.session_id}] Connection closed normally")
            self._state = ConnectionState.DISCONNECTED

        except ConnectionClosedError as e:
            logger.error(f"[{self.session_id}] Connection closed with error: {e}")
            self._state = ConnectionState.ERROR
            if self.on_error:
                await self.on_error(ConnectionError(str(e)))

        except asyncio.CancelledError:
            logger.debug(f"[{self.session_id}] Receive loop cancelled")
            raise

        except Exception as e:
            logger.exception(f"[{self.session_id}] Receive loop error: {e}")
            self._state = ConnectionState.ERROR
            if self.on_error:
                await self.on_error(PersonaPlexError(str(e)))

    async def _handle_message(self, raw_message: str | bytes) -> None:
        """
        Handle incoming message from PersonaPlex.

        Args:
            raw_message: Raw WebSocket message
        """
        try:
            if isinstance(raw_message, bytes):
                message = json.loads(raw_message.decode("utf-8"))
            else:
                message = json.loads(raw_message)

            msg_type = message.get("type")

            if msg_type == PersonaPlexMessageType.READY.value:
                await self._handle_ready(message)

            elif msg_type == PersonaPlexMessageType.TRANSCRIPT.value:
                await self._handle_transcript(message)

            elif msg_type == PersonaPlexMessageType.AUDIO_RESPONSE.value:
                await self._handle_audio(message)

            elif msg_type == PersonaPlexMessageType.SPEAKING.value:
                self._is_speaking = True
                logger.debug(f"[{self.session_id}] PersonaPlex started speaking")

            elif msg_type == PersonaPlexMessageType.STOPPED.value:
                self._is_speaking = False
                logger.debug(f"[{self.session_id}] PersonaPlex stopped speaking")

            elif msg_type == PersonaPlexMessageType.ERROR.value:
                await self._handle_error(message)

            else:
                logger.warning(f"[{self.session_id}] Unknown message type: {msg_type}")

        except json.JSONDecodeError as e:
            logger.error(f"[{self.session_id}] Invalid JSON message: {e}")

    async def _handle_ready(self, message: dict) -> None:
        """Handle ready message indicating configuration accepted."""
        self._state = ConnectionState.CONFIGURED
        logger.info(f"[{self.session_id}] PersonaPlex ready and configured")

    async def _handle_transcript(self, message: dict) -> None:
        """Handle transcript message from STT."""
        text = message.get("text", "")
        is_final = message.get("is_final", False)
        confidence = message.get("confidence", 1.0)

        if not text:
            return

        event = TranscriptEvent(
            text=text,
            is_final=is_final,
            confidence=confidence,
        )

        logger.debug(
            f"[{self.session_id}] Transcript: '{text}' "
            f"(final={is_final}, confidence={confidence:.2f})"
        )

        if self.on_transcript:
            await self.on_transcript(event)

    async def _handle_audio(self, message: dict) -> None:
        """Handle audio message from TTS (accepts both "audio" and legacy "data" keys)."""
        audio_base64 = message.get("audio") or message.get("data") or ""
        sample_rate = message.get("sample_rate", 24000)
        duration_ms = message.get("duration_ms", 0)
        is_final = message.get("is_final", True)

        if not audio_base64:
            return

        event = AudioEvent(
            audio_base64=audio_base64,
            sample_rate=sample_rate,
            duration_ms=duration_ms,
            is_final=is_final,
        )

        if self.on_audio:
            await self.on_audio(event)

    async def _handle_error(self, message: dict) -> None:
        """Handle error message from PersonaPlex."""
        error_msg = message.get("message", "Unknown error")
        error_code = message.get("code", "UNKNOWN")

        logger.error(f"[{self.session_id}] PersonaPlex error: {error_code} - {error_msg}")

        if self.on_error:
            await self.on_error(PersonaPlexError(error_msg, error_code))

    async def reconnect(self) -> bool:
        """
        Attempt to reconnect to PersonaPlex.

        Returns:
            True if reconnection successful, False otherwise
        """
        if self._reconnect_attempts >= self._max_reconnect_attempts:
            logger.error(f"[{self.session_id}] Max reconnect attempts reached")
            return False

        self._reconnect_attempts += 1
        delay = self._reconnect_delay * (2 ** (self._reconnect_attempts - 1))

        logger.info(
            f"[{self.session_id}] Reconnect attempt {self._reconnect_attempts} "
            f"in {delay:.1f}s"
        )

        await asyncio.sleep(delay)

        try:
            await self.disconnect()
            await self.connect()
            self._reconnect_attempts = 0
            return True

        except ConnectionError as e:
            logger.error(f"[{self.session_id}] Reconnect failed: {e}")
            return False


class PersonaPlexClientPool:
    """
    Pool of PersonaPlex clients for managing multiple concurrent sessions.

    Multi-tenant support for many companies, agents, concurrent calls.
    """

    def __init__(self, max_clients: int = 100):
        """
        Initialize client pool.

        Args:
            max_clients: Maximum number of concurrent clients
        """
        self._clients: dict[str, PersonaPlexClient] = {}
        self._max_clients = max_clients
        self._lock = asyncio.Lock()

    async def get_client(
        self,
        session_id: str,
        config: PersonaPlexConfig,
        on_transcript: TranscriptCallback | None = None,
        on_audio: AudioCallback | None = None,
        on_error: ErrorCallback | None = None,
        endpoint: str | None = None,
    ) -> PersonaPlexClient:
        """
        Get or create a client for a session.

        Args:
            session_id: Unique session identifier
            config: PersonaPlex configuration
            on_transcript: Transcript callback
            on_audio: Audio callback
            on_error: Error callback

        Returns:
            PersonaPlex client instance

        Raises:
            PersonaPlexError: If pool is at capacity
        """
        async with self._lock:
            if session_id in self._clients:
                return self._clients[session_id]

            if len(self._clients) >= self._max_clients:
                raise PersonaPlexError(
                    "Client pool at capacity",
                    "POOL_CAPACITY_EXCEEDED",
                )

            client = PersonaPlexClient(
                session_id=session_id,
                config=config,
                on_transcript=on_transcript,
                on_audio=on_audio,
                on_error=on_error,
                endpoint=endpoint,
            )

            self._clients[session_id] = client
            logger.info(f"Created PersonaPlex client for session {session_id}")

            return client

    async def remove_client(self, session_id: str) -> None:
        """
        Remove and disconnect a client.

        Args:
            session_id: Session identifier
        """
        async with self._lock:
            if session_id in self._clients:
                client = self._clients.pop(session_id)
                await client.disconnect()
                logger.info(f"Removed PersonaPlex client for session {session_id}")

    async def disconnect_all(self) -> None:
        """Disconnect all clients in the pool."""
        async with self._lock:
            for session_id, client in list(self._clients.items()):
                await client.disconnect()
            self._clients.clear()
            logger.info("All PersonaPlex clients disconnected")

    @property
    def active_count(self) -> int:
        """Get number of active clients."""
        return len(self._clients)


# Global client pool instance
_client_pool: PersonaPlexClientPool | None = None


def get_client_pool() -> PersonaPlexClientPool:
    """Get the global PersonaPlex client pool."""
    global _client_pool
    if _client_pool is None:
        _client_pool = PersonaPlexClientPool()
    return _client_pool
