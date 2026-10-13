"""
Twilio integration handler for telephony operations.

Twilio provides telephony infrastructure (SIP, phone numbers, media streams).

Handles:
- TwiML generation for call control
- MediaStream setup for bidirectional audio
- Call status management
- Recording configuration
- Phone number operations
"""

import hashlib
import hmac
import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any
from urllib.parse import urlencode

from twilio.rest import Client as TwilioClient
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream, Say, Gather
from twilio.request_validator import RequestValidator

from app.config import get_settings

logger = logging.getLogger(__name__)


class CallDirection(str, Enum):
    """Call direction."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


class TwilioCallStatus(str, Enum):
    """Twilio call status values."""

    QUEUED = "queued"
    RINGING = "ringing"
    IN_PROGRESS = "in-progress"
    COMPLETED = "completed"
    BUSY = "busy"
    NO_ANSWER = "no-answer"
    CANCELED = "canceled"
    FAILED = "failed"


@dataclass
class TwilioCallInfo:
    """Information about a Twilio call."""

    call_sid: str
    account_sid: str
    from_number: str
    to_number: str
    direction: CallDirection
    status: TwilioCallStatus
    caller_name: str | None = None
    forwarded_from: str | None = None
    caller_city: str | None = None
    caller_state: str | None = None
    caller_country: str | None = None

    @classmethod
    def from_webhook_params(cls, params: dict[str, str]) -> "TwilioCallInfo":
        """
        Create TwilioCallInfo from webhook parameters.

        Args:
            params: Dictionary of webhook parameters

        Returns:
            TwilioCallInfo instance
        """
        direction = (
            CallDirection.INBOUND
            if params.get("Direction", "inbound") == "inbound"
            else CallDirection.OUTBOUND
        )

        status_str = params.get("CallStatus", "ringing")
        status = TwilioCallStatus(status_str.replace("_", "-"))

        return cls(
            call_sid=params.get("CallSid", ""),
            account_sid=params.get("AccountSid", ""),
            from_number=params.get("From", ""),
            to_number=params.get("To", ""),
            direction=direction,
            status=status,
            caller_name=params.get("CallerName"),
            forwarded_from=params.get("ForwardedFrom"),
            caller_city=params.get("FromCity"),
            caller_state=params.get("FromState"),
            caller_country=params.get("FromCountry"),
        )


class TwilioHandlerError(Exception):
    """Base exception for Twilio handler errors."""

    def __init__(self, message: str, code: str = "TWILIO_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class InvalidSignatureError(TwilioHandlerError):
    """Raised when webhook signature validation fails."""

    def __init__(self):
        super().__init__(
            "Invalid Twilio signature",
            "INVALID_SIGNATURE",
        )


class TwilioHandler:
    """
    Handler for Twilio telephony operations.

    Manages TwiML generation, MediaStream setup, and Twilio API interactions.
    """

    def __init__(self, account_sid: str | None = None, auth_token: str | None = None):
        """
        Initialize Twilio handler.

        Credentials default to the environment (TWILIO_ACCOUNT_SID/AUTH_TOKEN);
        pass explicit values to act on behalf of a tenant who saved their own
        credentials in Settings (see ``for_user``).
        """
        settings = get_settings()

        self._account_sid = account_sid or settings.twilio_account_sid
        self._auth_token = auth_token or settings.twilio_auth_token
        self._api_key_sid = settings.twilio_api_key_sid
        self._api_key_secret = settings.twilio_api_key_secret

        # Initialize Twilio client
        if self._account_sid and self._auth_token:
            self._client = TwilioClient(self._account_sid, self._auth_token)
        else:
            self._client = None
            logger.warning("Twilio credentials not configured")

        # Request validator for webhook signature verification
        if self._auth_token:
            self._validator = RequestValidator(self._auth_token)
        else:
            self._validator = None

        # Backend URL for webhooks
        self._backend_url = settings.backend_url

    @classmethod
    async def for_user(cls, db, user_id: str) -> "TwilioHandler":
        """Handler using the tenant's saved Twilio credentials (env fallback)."""
        from app.services.credentials import CredentialResolver

        creds = await CredentialResolver(db).twilio(user_id)
        if creds:
            return cls(account_sid=creds.account_sid, auth_token=creds.auth_token)
        return cls()

    @property
    def is_configured(self) -> bool:
        return self._client is not None

    @staticmethod
    def signature_is_valid(auth_token: str, url: str, params: dict[str, str], signature: str) -> bool:
        return RequestValidator(auth_token).validate(url, params, signature)

    def validate_request(
        self,
        url: str,
        params: dict[str, str],
        signature: str,
    ) -> bool:
        """
        Validate Twilio webhook request signature.

        Webhook signature verification (Twilio, Stripe).

        Args:
            url: Full URL of the webhook endpoint
            params: Request parameters
            signature: X-Twilio-Signature header value

        Returns:
            True if signature is valid

        Raises:
            InvalidSignatureError: If signature is invalid
        """
        if self._validator is None:
            logger.warning("Signature validation skipped: no auth token")
            return True

        is_valid = self._validator.validate(url, params, signature)

        if not is_valid:
            logger.warning("Invalid Twilio signature received")
            raise InvalidSignatureError()

        return True

    def generate_answer_twiml(
        self,
        session_id: str,
        greeting: str | None = None,
        websocket_url: str | None = None,
        stream_token: str | None = None,
    ) -> str:
        """
        Generate TwiML for answering an inbound call with MediaStream.

        This sets up bidirectional audio streaming via WebSocket.

        Args:
            session_id: Unique session identifier for the call
            greeting: Optional greeting to play before connecting
            websocket_url: WebSocket URL for media stream (auto-generated if not provided)

        Returns:
            TwiML XML string
        """
        response = VoiceResponse()

        # Optional greeting before connecting to AI
        if greeting:
            response.say(greeting, voice="Polly.Joanna")

        # Set up MediaStream for bidirectional audio
        if websocket_url is None:
            # Convert http(s):// to ws(s)://
            ws_scheme = "wss" if self._backend_url.startswith("https") else "ws"
            ws_base = self._backend_url.replace("https://", "").replace("http://", "")
            websocket_url = f"{ws_scheme}://{ws_base}/api/v1/voice/stream/{session_id}"

        connect = Connect()
        stream = Stream(url=websocket_url)

        # Configure stream parameters
        stream.parameter(name="session_id", value=session_id)
        if stream_token:
            stream.parameter(name="token", value=stream_token)

        connect.append(stream)
        response.append(connect)

        twiml = str(response)
        logger.debug(f"Generated answer TwiML for session {session_id}")

        return twiml

    def generate_outbound_twiml(
        self,
        session_id: str,
        websocket_url: str | None = None,
        stream_token: str | None = None,
    ) -> str:
        """
        Generate TwiML for outbound call with MediaStream.

        Args:
            session_id: Unique session identifier
            websocket_url: WebSocket URL for media stream

        Returns:
            TwiML XML string
        """
        response = VoiceResponse()

        # Set up MediaStream
        if websocket_url is None:
            ws_scheme = "wss" if self._backend_url.startswith("https") else "ws"
            ws_base = self._backend_url.replace("https://", "").replace("http://", "")
            websocket_url = f"{ws_scheme}://{ws_base}/api/v1/voice/stream/{session_id}"

        connect = Connect()
        stream = Stream(url=websocket_url)
        stream.parameter(name="session_id", value=session_id)
        if stream_token:
            stream.parameter(name="token", value=stream_token)

        connect.append(stream)
        response.append(connect)

        return str(response)

    def generate_hold_twiml(
        self,
        message: str = "Please hold while we connect you.",
        music_url: str | None = None,
    ) -> str:
        """
        Generate TwiML for putting caller on hold.

        Args:
            message: Message to play
            music_url: URL to hold music

        Returns:
            TwiML XML string
        """
        response = VoiceResponse()
        response.say(message, voice="Polly.Joanna")

        if music_url:
            response.play(music_url, loop=10)
        else:
            # Default to silence with periodic message
            response.pause(length=30)
            response.say("Thank you for holding.", voice="Polly.Joanna")
            response.redirect("")  # Loop back

        return str(response)

    def generate_transfer_twiml(
        self,
        destination: str,
        announce: bool = True,
        whisper: str | None = None,
    ) -> str:
        """
        Generate TwiML for transferring a call.

        Args:
            destination: Phone number or SIP URI to transfer to
            announce: Whether to announce the transfer
            whisper: Message to whisper to the recipient

        Returns:
            TwiML XML string
        """
        response = VoiceResponse()

        if announce:
            response.say(
                "Please hold while I transfer your call.",
                voice="Polly.Joanna",
            )

        dial = response.dial(
            caller_id=None,  # Will use original caller ID
            timeout=30,
            action=f"{self._backend_url}/api/v1/webhooks/twilio/voice/transfer-status",
        )

        if whisper:
            # Use URL parameter for whisper
            dial.number(
                destination,
                url=f"{self._backend_url}/api/v1/webhooks/twilio/voice/whisper?"
                    f"message={whisper}",
            )
        else:
            dial.number(destination)

        return str(response)

    def generate_hangup_twiml(
        self,
        message: str | None = None,
    ) -> str:
        """
        Generate TwiML for ending a call.

        Args:
            message: Optional goodbye message

        Returns:
            TwiML XML string
        """
        response = VoiceResponse()

        if message:
            response.say(message, voice="Polly.Joanna")

        response.hangup()

        return str(response)

    def generate_gather_twiml(
        self,
        prompt: str,
        action_url: str,
        num_digits: int = 1,
        timeout: int = 5,
    ) -> str:
        """
        Generate TwiML for gathering DTMF input.

        Args:
            prompt: Message to play
            action_url: URL to POST gathered digits to
            num_digits: Number of digits to gather
            timeout: Timeout in seconds

        Returns:
            TwiML XML string
        """
        response = VoiceResponse()

        gather = Gather(
            num_digits=num_digits,
            action=action_url,
            timeout=timeout,
        )
        gather.say(prompt, voice="Polly.Joanna")

        response.append(gather)

        # If no input, redirect
        response.redirect(action_url + "?Digits=timeout")

        return str(response)

    async def initiate_outbound_call(
        self,
        to_number: str,
        from_number: str,
        session_id: str,
        status_callback_url: str | None = None,
    ) -> str:
        """
        Initiate an outbound call via Twilio API.

        Args:
            to_number: Destination phone number
            from_number: Caller ID (must be a verified Twilio number)
            session_id: Session identifier
            status_callback_url: URL for status updates

        Returns:
            Twilio Call SID

        Raises:
            TwilioHandlerError: If call initiation fails
        """
        if self._client is None:
            raise TwilioHandlerError(
                "Twilio client not configured",
                "NOT_CONFIGURED",
            )

        twiml_url = (
            f"{self._backend_url}/api/v1/webhooks/twilio/voice/outbound?"
            f"session_id={session_id}"
        )

        if status_callback_url is None:
            status_callback_url = (
                f"{self._backend_url}/api/v1/webhooks/twilio/voice/status"
            )

        try:
            call = self._client.calls.create(
                to=to_number,
                from_=from_number,
                url=twiml_url,
                status_callback=status_callback_url,
                status_callback_event=["initiated", "ringing", "answered", "completed"],
                status_callback_method="POST",
                record=True,
                recording_status_callback=(
                    f"{self._backend_url}/api/v1/webhooks/twilio/voice/recording"
                ),
            )

            logger.info(
                f"Outbound call initiated: {call.sid} "
                f"to {to_number} from {from_number}"
            )

            return call.sid

        except Exception as e:
            logger.error(f"Failed to initiate outbound call: {e}")
            raise TwilioHandlerError(f"Failed to initiate call: {e}")

    async def end_call(self, call_sid: str) -> None:
        """
        End an active call.

        Args:
            call_sid: Twilio Call SID
        """
        if self._client is None:
            raise TwilioHandlerError("Twilio client not configured", "NOT_CONFIGURED")

        try:
            self._client.calls(call_sid).update(status="completed")
            logger.info(f"Call ended: {call_sid}")
        except Exception as e:
            logger.error(f"Failed to end call {call_sid}: {e}")
            raise TwilioHandlerError(f"Failed to end call: {e}")

    async def get_recording(self, recording_sid: str) -> dict[str, Any]:
        """
        Get recording details.

        Args:
            recording_sid: Twilio Recording SID

        Returns:
            Recording details dict
        """
        if self._client is None:
            raise TwilioHandlerError("Twilio client not configured", "NOT_CONFIGURED")

        try:
            recording = self._client.recordings(recording_sid).fetch()
            return {
                "sid": recording.sid,
                "call_sid": recording.call_sid,
                "duration": recording.duration,
                "status": recording.status,
                "uri": recording.uri,
                "media_url": f"https://api.twilio.com{recording.uri.replace('.json', '.mp3')}",
            }
        except Exception as e:
            logger.error(f"Failed to get recording {recording_sid}: {e}")
            raise TwilioHandlerError(f"Failed to get recording: {e}")

    async def search_available_numbers(
        self,
        country: str = "US",
        area_code: str | None = None,
        contains: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Search for available phone numbers.

        Args:
            country: Country code
            area_code: Preferred area code
            contains: Pattern to match
            limit: Maximum numbers to return

        Returns:
            List of available number details
        """
        if self._client is None:
            raise TwilioHandlerError("Twilio client not configured", "NOT_CONFIGURED")

        try:
            kwargs = {"limit": limit}
            if area_code:
                kwargs["area_code"] = area_code
            if contains:
                kwargs["contains"] = contains

            numbers = self._client.available_phone_numbers(country).local.list(**kwargs)

            return [
                {
                    "phone_number": n.phone_number,
                    "friendly_name": n.friendly_name,
                    "locality": n.locality,
                    "region": n.region,
                    "capabilities": {
                        "voice": n.capabilities.get("voice", False),
                        "sms": n.capabilities.get("sms", False),
                        "mms": n.capabilities.get("mms", False),
                    },
                }
                for n in numbers
            ]
        except Exception as e:
            logger.error(f"Failed to search numbers: {e}")
            raise TwilioHandlerError(f"Failed to search numbers: {e}")

    async def purchase_phone_number(
        self,
        phone_number: str,
        friendly_name: str | None = None,
        voice_url: str | None = None,
    ) -> dict[str, Any]:
        """
        Purchase a phone number.

        Args:
            phone_number: Phone number to purchase
            friendly_name: Friendly name for the number
            voice_url: URL for incoming voice calls

        Returns:
            Purchased number details
        """
        if self._client is None:
            raise TwilioHandlerError("Twilio client not configured", "NOT_CONFIGURED")

        if voice_url is None:
            voice_url = f"{self._backend_url}/api/v1/webhooks/twilio/voice"

        try:
            number = self._client.incoming_phone_numbers.create(
                phone_number=phone_number,
                friendly_name=friendly_name,
                voice_url=voice_url,
                voice_method="POST",
                status_callback=f"{self._backend_url}/api/v1/webhooks/twilio/voice/status",
                status_callback_method="POST",
            )

            logger.info(f"Phone number purchased: {number.phone_number} ({number.sid})")

            return {
                "sid": number.sid,
                "phone_number": number.phone_number,
                "friendly_name": number.friendly_name,
            }
        except Exception as e:
            logger.error(f"Failed to purchase number {phone_number}: {e}")
            raise TwilioHandlerError(f"Failed to purchase number: {e}")

    async def release_phone_number(self, number_sid: str) -> None:
        """
        Release a phone number.

        Args:
            number_sid: Twilio phone number SID
        """
        if self._client is None:
            raise TwilioHandlerError("Twilio client not configured", "NOT_CONFIGURED")

        try:
            self._client.incoming_phone_numbers(number_sid).delete()
            logger.info(f"Phone number released: {number_sid}")
        except Exception as e:
            logger.error(f"Failed to release number {number_sid}: {e}")
            raise TwilioHandlerError(f"Failed to release number: {e}")

    @property
    def inbound_voice_url(self) -> str:
        return f"{self._backend_url.rstrip('/')}/api/v1/webhooks/twilio/voice"

    @property
    def status_callback_url(self) -> str:
        return f"{self._backend_url.rstrip('/')}/api/v1/webhooks/twilio/voice/status"

    async def lookup_phone_number(self, phone_number: str) -> dict | None:
        """
        Find an incoming phone number owned by this Twilio account.

        Returns {"sid", "phone_number", "friendly_name", "voice_url"} or None.
        """
        if self._client is None:
            raise TwilioHandlerError("Twilio client not configured", "NOT_CONFIGURED")

        def _fetch():
            return self._client.incoming_phone_numbers.list(phone_number=phone_number, limit=1)

        try:
            numbers = await asyncio.get_running_loop().run_in_executor(None, _fetch)
        except Exception as e:
            logger.error(f"Failed to look up number {phone_number}: {e}")
            raise TwilioHandlerError(f"Failed to look up number: {e}")

        if not numbers:
            return None
        n = numbers[0]
        return {
            "sid": n.sid,
            "phone_number": n.phone_number,
            "friendly_name": n.friendly_name,
            "voice_url": getattr(n, "voice_url", None),
        }

    async def configure_phone_number(
        self,
        number_sid: str,
        voice_url: str | None = None,
        friendly_name: str | None = None,
        status_callback: str | None = None,
    ) -> None:
        """
        Point a Twilio number's voice webhook (and status callback) at this backend.

        Args:
            number_sid: Twilio phone number SID
            voice_url: URL for incoming voice calls (default: this backend's inbound webhook)
            friendly_name: Friendly name
            status_callback: Status callback URL (default: this backend's status webhook)
        """
        if self._client is None:
            raise TwilioHandlerError("Twilio client not configured", "NOT_CONFIGURED")

        update_kwargs: dict = {
            "voice_url": voice_url or self.inbound_voice_url,
            "voice_method": "POST",
            "status_callback": status_callback or self.status_callback_url,
            "status_callback_method": "POST",
        }
        if friendly_name:
            update_kwargs["friendly_name"] = friendly_name

        def _update():
            return self._client.incoming_phone_numbers(number_sid).update(**update_kwargs)

        try:
            await asyncio.get_running_loop().run_in_executor(None, _update)
            logger.info(f"Phone number {number_sid} webhooks -> {update_kwargs['voice_url']}")
        except Exception as e:
            logger.error(f"Failed to configure number {number_sid}: {e}")
            raise TwilioHandlerError(f"Failed to configure number: {e}")


# Global handler instance
_twilio_handler: TwilioHandler | None = None


def get_twilio_handler() -> TwilioHandler:
    """Get the global Twilio handler instance."""
    global _twilio_handler
    if _twilio_handler is None:
        _twilio_handler = TwilioHandler()
    return _twilio_handler
