"""
VoicePlex Voice Server - speech-to-text and text-to-speech over one WebSocket.

WHAT THIS IS
    A conventional speech pipeline server used by the VoicePlex backend:

        caller audio  --> STT  --> {"type": "transcript"}   (backend sends it to Claude)
        Claude text   --> TTS  --> {"type": "audio"}        (backend streams it to Twilio)

    Claude (running inside the VoicePlex backend) is the conversational brain and
    performs tool calls.  This server is deliberately "dumb": it only converts
    audio <-> text.

WHAT THIS IS NOT
    NVIDIA PersonaPlex.  PersonaPlex-7B is a full-duplex *speech-to-speech* model
    (Moshi architecture) that generates its own replies; it cannot be driven as a
    TTS or STT engine, which is what the backend needs.  Earlier versions of this
    directory tried to coerce it into that role with APIs that do not exist.  If
    PersonaPlex is ever adopted it must replace Claude as the brain, which is a
    different architecture (see ARCHITECTURE.md in the repo root).

PROTOCOL
    See PROTOCOL.md next to this file.  Summary (all JSON text frames):

      client -> server                      server -> client
      {"type":"ping"}                       {"type":"pong"}
      {"type":"config", voice_id, speed,..} {"type":"ready"}
      {"type":"tts", text, voice_id, speed} {"type":"audio", audio, sample_rate, duration_ms, is_final:true}
      {"type":"speak", text}                {"type":"speaking"} then N x {"type":"audio", ..., is_final}
                                            then {"type":"stopped"}
      {"type":"audio", audio(b64 pcm16)}    {"type":"transcript", text, is_final, confidence}
      {"type":"interrupt"}                  {"type":"stopped"}
      {"type":"end"}                        (socket closed)
      {"type":"list_voices"}                {"type":"voices", voices:[...]}

    Audio is always 16-bit signed little-endian PCM, mono, 24 kHz, base64 in JSON.

BACKENDS (auto-detected, override with env VOICE_TTS_BACKEND / VOICE_STT_BACKEND)
    TTS:  edge    - Microsoft Edge neural voices via `edge-tts` (+ ffmpeg).  No GPU.
          tone    - synthetic placeholder so connectivity can be tested without
                    network access.  Logs loudly that it is a placeholder.
    STT:  faster_whisper - `faster-whisper` (CTranslate2), CPU or GPU.
          whisper        - `openai-whisper`.
          none           - transcripts disabled; only TTS works.

RUN
    pip install -r requirements.txt        # aiohttp numpy edge-tts faster-whisper
    apt-get install -y ffmpeg              # needed by edge backend (mp3 -> pcm)
    python voice_server.py                 # ws://0.0.0.0:8765/ws   http://0.0.0.0:8765/health
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import shutil
import struct
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np
from aiohttp import WSMsgType, web

logging.basicConfig(
    level=os.environ.get("VOICE_LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("voice-server")

SAMPLE_RATE = 24_000          # wire format (backend and Twilio resampling assume this)
STT_SAMPLE_RATE = 16_000      # whisper input rate
AUDIO_CHUNK_MS = 100          # size of streamed TTS frames for "speak"

# VAD / utterance segmentation
VAD_ENERGY_THRESHOLD = float(os.environ.get("VOICE_VAD_THRESHOLD", "400"))  # RMS on int16 scale
VAD_MIN_SPEECH_MS = 250
VAD_END_SILENCE_MS = 700
VAD_MAX_UTTERANCE_MS = 15_000


# ---------------------------------------------------------------------------
# Voice catalogue
# ---------------------------------------------------------------------------
# Voice ids are the ones the VoicePlex backend/frontend show.  Each maps to an
# Edge TTS neural voice.  Unknown ids fall back to DEFAULT_VOICE.
VOICES: dict[str, dict[str, str]] = {
    "NATF0": {"name": "Natural Female", "edge": "en-US-JennyNeural", "gender": "female"},
    "NATM0": {"name": "Natural Male", "edge": "en-US-GuyNeural", "gender": "male"},
    "NATF1": {"name": "Natural Female Alt", "edge": "en-US-AriaNeural", "gender": "female"},
    "NATM1": {"name": "Natural Male Alt", "edge": "en-US-DavisNeural", "gender": "male"},
    "PROF0": {"name": "Professional Female", "edge": "en-US-NancyNeural", "gender": "female"},
    "PROM0": {"name": "Professional Male", "edge": "en-US-SteffanNeural", "gender": "male"},
    "PROF1": {"name": "Professional Female Alt", "edge": "en-GB-SoniaNeural", "gender": "female"},
    "PROM1": {"name": "Professional Male Alt", "edge": "en-GB-RyanNeural", "gender": "male"},
    "CALM0": {"name": "Calm Female", "edge": "en-US-SaraNeural", "gender": "female"},
    "CALM1": {"name": "Calm Male", "edge": "en-US-JasonNeural", "gender": "male"},
    "ENRG0": {"name": "Energetic Female", "edge": "en-AU-NatashaNeural", "gender": "female"},
    "ENRG1": {"name": "Energetic Male", "edge": "en-AU-WilliamNeural", "gender": "male"},
}
DEFAULT_VOICE = "NATF0"


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------
def pcm16_to_float(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


def float_to_pcm16(x: np.ndarray) -> bytes:
    return (np.clip(x, -1.0, 1.0) * 32767).astype(np.int16).tobytes()


def resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    """Linear-interpolation resampler; adequate for speech STT input."""
    if src == dst or x.size == 0:
        return x
    n_out = int(round(x.size * dst / src))
    src_t = np.linspace(0.0, 1.0, x.size, endpoint=False)
    dst_t = np.linspace(0.0, 1.0, n_out, endpoint=False)
    return np.interp(dst_t, src_t, x).astype(np.float32)


def rms_int16(pcm: bytes) -> float:
    if not pcm:
        return 0.0
    a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(a * a))) if a.size else 0.0


def wav_bytes(pcm: bytes, rate: int = SAMPLE_RATE) -> bytes:
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(pcm), b"WAVE", b"fmt ", 16, 1, 1,
        rate, rate * 2, 2, 16, b"data", len(pcm),
    )
    return header + pcm


# ---------------------------------------------------------------------------
# TTS backends
# ---------------------------------------------------------------------------
class TTSBackend(Protocol):
    name: str

    async def synthesize(self, text: str, voice_id: str, speed: float) -> bytes:
        """Return PCM16 mono @ SAMPLE_RATE."""


class ToneTTS:
    """Placeholder: produces an audible tone of roughly the right length.

    Exists so the whole pipeline (backend -> server -> Twilio) can be smoke-tested
    without network access.  NEVER use in production.
    """

    name = "tone (PLACEHOLDER - not real speech)"

    async def synthesize(self, text: str, voice_id: str, speed: float) -> bytes:
        words = max(1, len(text.split()))
        duration = max(0.4, words * 0.28 / max(speed, 0.1))
        t = np.linspace(0, duration, int(duration * SAMPLE_RATE), endpoint=False)
        freq = 220 + 60 * np.sin(2 * np.pi * 0.7 * t)
        env = np.minimum(1.0, t * 20) * np.exp(-t * 0.6)
        return float_to_pcm16(0.25 * env * np.sin(2 * np.pi * freq * t))


class EdgeTTS:
    """Microsoft Edge neural TTS via the `edge-tts` package. MP3 -> PCM via ffmpeg."""

    name = "edge-tts"

    def __init__(self) -> None:
        import edge_tts  # noqa: F401  (import check)

        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg not found on PATH (required to decode Edge TTS mp3)")

    async def synthesize(self, text: str, voice_id: str, speed: float) -> bytes:
        import edge_tts

        voice = VOICES.get(voice_id, VOICES[DEFAULT_VOICE])["edge"]
        pct = int(round((speed - 1.0) * 100))
        rate = f"{'+' if pct >= 0 else ''}{pct}%"
        comm = edge_tts.Communicate(text, voice, rate=rate)
        mp3 = b"".join(
            [c["data"] async for c in comm.stream() if c["type"] == "audio"]
        )
        if not mp3:
            raise RuntimeError("edge-tts returned no audio")
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-f", "s16le",
            "-acodec", "pcm_s16le", "-ar", str(SAMPLE_RATE), "-ac", "1", "pipe:1",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        pcm, err = await proc.communicate(mp3)
        if proc.returncode != 0 or not pcm:
            raise RuntimeError(f"ffmpeg decode failed: {err.decode(errors='ignore')[:200]}")
        return pcm


def build_tts() -> TTSBackend:
    want = os.environ.get("VOICE_TTS_BACKEND", "auto").lower()
    if want in ("auto", "edge"):
        try:
            tts = EdgeTTS()
            logger.info("TTS backend: edge-tts")
            return tts
        except Exception as e:  # noqa: BLE001
            if want == "edge":
                raise
            logger.warning("edge-tts unavailable (%s); falling back to placeholder tone TTS", e)
    logger.warning("TTS backend: PLACEHOLDER TONE - output is not speech. Install edge-tts + ffmpeg.")
    return ToneTTS()


# ---------------------------------------------------------------------------
# STT backends
# ---------------------------------------------------------------------------
class STTBackend(Protocol):
    name: str

    async def transcribe(self, pcm: bytes) -> tuple[str, float]:
        """pcm is PCM16 mono @ SAMPLE_RATE. Returns (text, confidence)."""


class FasterWhisperSTT:
    name = "faster-whisper"

    def __init__(self, model_size: str) -> None:
        from faster_whisper import WhisperModel

        device = "cuda" if _cuda_available() else "cpu"
        compute = "float16" if device == "cuda" else "int8"
        self._model = WhisperModel(model_size, device=device, compute_type=compute)
        logger.info("faster-whisper '%s' loaded on %s", model_size, device)

    async def transcribe(self, pcm: bytes) -> tuple[str, float]:
        audio = resample(pcm16_to_float(pcm), SAMPLE_RATE, STT_SAMPLE_RATE)

        def _run() -> tuple[str, float]:
            segments, _info = self._model.transcribe(audio, language="en", beam_size=1, vad_filter=False)
            texts, probs = [], []
            for s in segments:
                texts.append(s.text.strip())
                probs.append(float(np.exp(s.avg_logprob)))
            return " ".join(t for t in texts if t), (float(np.mean(probs)) if probs else 0.0)

        return await asyncio.get_running_loop().run_in_executor(None, _run)


class OpenAIWhisperSTT:
    name = "openai-whisper"

    def __init__(self, model_size: str) -> None:
        import whisper

        device = "cuda" if _cuda_available() else "cpu"
        self._model = whisper.load_model(model_size, device=device)
        self._fp16 = device == "cuda"
        logger.info("openai-whisper '%s' loaded on %s", model_size, device)

    async def transcribe(self, pcm: bytes) -> tuple[str, float]:
        audio = resample(pcm16_to_float(pcm), SAMPLE_RATE, STT_SAMPLE_RATE)

        def _run() -> tuple[str, float]:
            r = self._model.transcribe(audio, language="en", fp16=self._fp16)
            return r.get("text", "").strip(), 0.9

        return await asyncio.get_running_loop().run_in_executor(None, _run)


def _cuda_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:  # noqa: BLE001
        return False


def build_stt() -> STTBackend | None:
    want = os.environ.get("VOICE_STT_BACKEND", "auto").lower()
    size = os.environ.get("VOICE_STT_MODEL", "base.en")
    if want == "none":
        logger.warning("STT disabled by VOICE_STT_BACKEND=none")
        return None
    if want in ("auto", "faster_whisper"):
        try:
            return FasterWhisperSTT(size)
        except Exception as e:  # noqa: BLE001
            if want == "faster_whisper":
                raise
            logger.info("faster-whisper unavailable (%s)", e)
    if want in ("auto", "whisper"):
        try:
            return OpenAIWhisperSTT(size)
        except Exception as e:  # noqa: BLE001
            if want == "whisper":
                raise
            logger.info("openai-whisper unavailable (%s)", e)
    logger.warning("STT backend: NONE - caller speech will not be transcribed. "
                   "pip install faster-whisper")
    return None


# ---------------------------------------------------------------------------
# Utterance detection (energy VAD)
# ---------------------------------------------------------------------------
@dataclass
class UtteranceDetector:
    """Accumulates PCM chunks and yields a complete utterance after end-of-speech silence."""

    buffer: bytearray = field(default_factory=bytearray)
    speech_ms: float = 0.0
    silence_ms: float = 0.0
    in_speech: bool = False

    def feed(self, pcm: bytes) -> bytes | None:
        ms = len(pcm) / 2 / SAMPLE_RATE * 1000
        loud = rms_int16(pcm) >= VAD_ENERGY_THRESHOLD
        if loud:
            if not self.in_speech:
                self.in_speech = True
                self.speech_ms = 0.0
            self.speech_ms += ms
            self.silence_ms = 0.0
            self.buffer.extend(pcm)
        elif self.in_speech:
            self.silence_ms += ms
            self.buffer.extend(pcm)
            if self.silence_ms >= VAD_END_SILENCE_MS:
                return self._flush()
        total_ms = len(self.buffer) / 2 / SAMPLE_RATE * 1000
        if self.in_speech and total_ms >= VAD_MAX_UTTERANCE_MS:
            return self._flush()
        return None

    def _flush(self) -> bytes | None:
        utt = bytes(self.buffer)
        enough = self.speech_ms >= VAD_MIN_SPEECH_MS
        self.buffer.clear()
        self.in_speech = False
        self.speech_ms = self.silence_ms = 0.0
        return utt if enough else None


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
@dataclass
class Session:
    id: str
    ws: web.WebSocketResponse
    voice_id: str = DEFAULT_VOICE
    speed: float = 1.0
    configured: bool = False
    speaking_task: asyncio.Task | None = None
    vad: UtteranceDetector = field(default_factory=UtteranceDetector)
    stt_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class VoiceServer:
    def __init__(self) -> None:
        self.tts = build_tts()
        self.stt = build_stt()
        self.sessions: dict[str, Session] = {}
        self._counter = 0
        self.started = time.time()

    # ---- HTTP -------------------------------------------------------------
    async def health(self, request: web.Request) -> web.Response:
        return web.json_response({
            "status": "ok",
            "server": "voiceplex-voice-server",
            "tts": self.tts.name,
            "stt": self.stt.name if self.stt else "none",
            "sample_rate": SAMPLE_RATE,
            "active_sessions": len(self.sessions),
            "uptime_s": int(time.time() - self.started),
        })

    async def root(self, request: web.Request) -> web.StreamResponse:
        # Backends sometimes configure the URL without /ws; accept upgrades on / too.
        if request.headers.get("Upgrade", "").lower() == "websocket":
            return await self.websocket(request)
        return await self.health(request)

    # ---- WebSocket --------------------------------------------------------
    async def websocket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=16 * 1024 * 1024)
        await ws.prepare(request)
        self._counter += 1
        s = Session(id=f"s{self._counter}", ws=ws)
        self.sessions[s.id] = s
        logger.info("[%s] connected from %s", s.id, request.remote)
        await self._send(s, {"type": "connected", "server": "voiceplex-voice-server",
                             "tts": self.tts.name, "stt": self.stt.name if self.stt else "none"})
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        await self._send(s, {"type": "error", "message": "invalid JSON"})
                        continue
                    await self._dispatch(s, data)
                elif msg.type == WSMsgType.BINARY:
                    await self._on_audio(s, msg.data)
                elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                    break
        finally:
            await self._cancel_speaking(s)
            self.sessions.pop(s.id, None)
            logger.info("[%s] disconnected", s.id)
        return ws

    async def _dispatch(self, s: Session, data: dict[str, Any]) -> None:
        t = data.get("type")
        if t == "ping":
            await self._send(s, {"type": "pong", "status": "connected"})
        elif t == "config":
            s.voice_id = data.get("voice_id") or DEFAULT_VOICE
            s.speed = float(data.get("speed") or 1.0)
            s.configured = True
            logger.info("[%s] configured voice=%s speed=%.2f", s.id, s.voice_id, s.speed)
            await self._send(s, {"type": "ready", "session_id": s.id})
        elif t == "tts":
            await self._on_tts(s, data)
        elif t == "speak":
            await self._on_speak(s, data)
        elif t == "audio":
            raw = data.get("audio") or data.get("data") or ""
            if raw:
                await self._on_audio(s, base64.b64decode(raw))
        elif t == "interrupt":
            if not await self._cancel_speaking(s):
                # nothing was playing; the cancelled task's finally would otherwise have sent this
                await self._send(s, {"type": "stopped", "reason": "interrupted"})
        elif t == "end":
            await self._cancel_speaking(s)
            await s.ws.close()
        elif t == "list_voices":
            await self._send(s, {"type": "voices", "voices": [
                {"id": k, **{kk: vv for kk, vv in v.items() if kk != "edge"}} for k, v in VOICES.items()
            ]})
        else:
            await self._send(s, {"type": "error", "message": f"unknown message type: {t}"})

    # ---- TTS --------------------------------------------------------------
    async def _on_tts(self, s: Session, data: dict[str, Any]) -> None:
        """One-shot synthesis (voice preview): whole clip in a single message."""
        text = (data.get("text") or "").strip()
        if not text:
            await self._send(s, {"type": "error", "message": "no text"})
            return
        voice = data.get("voice_id") or s.voice_id
        speed = float(data.get("speed") or s.speed)
        t0 = time.time()
        try:
            pcm = await self.tts.synthesize(text, voice, speed)
        except Exception as e:  # noqa: BLE001
            logger.exception("[%s] tts failed", s.id)
            await self._send(s, {"type": "error", "message": f"tts failed: {e}"})
            return
        dur = int(len(pcm) / 2 / SAMPLE_RATE * 1000)
        logger.info("[%s] tts %d chars -> %d ms audio in %.0f ms", s.id, len(text), dur, (time.time() - t0) * 1000)
        await self._send(s, {"type": "audio", "audio": base64.b64encode(pcm).decode(),
                             "sample_rate": SAMPLE_RATE, "duration_ms": dur, "is_final": True})

    async def _on_speak(self, s: Session, data: dict[str, Any]) -> None:
        """Live-call synthesis: streamed in ~100 ms frames, interruptible."""
        text = (data.get("text") or "").strip()
        if not text:
            return
        await self._cancel_speaking(s)
        s.speaking_task = asyncio.create_task(self._speak_stream(s, text))

    async def _speak_stream(self, s: Session, text: str) -> None:
        await self._send(s, {"type": "speaking"})
        try:
            pcm = await self.tts.synthesize(text, s.voice_id, s.speed)
            frame = int(SAMPLE_RATE * AUDIO_CHUNK_MS / 1000) * 2
            frames = [pcm[i:i + frame] for i in range(0, len(pcm), frame)] or [b""]
            for i, chunk in enumerate(frames):
                await self._send(s, {
                    "type": "audio", "audio": base64.b64encode(chunk).decode(),
                    "sample_rate": SAMPLE_RATE,
                    "duration_ms": int(len(chunk) / 2 / SAMPLE_RATE * 1000),
                    "is_final": i == len(frames) - 1,
                })
                # pace slightly faster than realtime so the client buffer never starves
                await asyncio.sleep(AUDIO_CHUNK_MS / 1000 * 0.8)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception("[%s] speak failed", s.id)
            await self._send(s, {"type": "error", "message": f"tts failed: {e}"})
        finally:
            await self._send(s, {"type": "stopped"})

    async def _cancel_speaking(self, s: Session) -> bool:
        """Cancel in-flight speech. Returns True if something was cancelled."""
        task, s.speaking_task = s.speaking_task, None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            return True
        return False

    # ---- STT --------------------------------------------------------------
    async def _on_audio(self, s: Session, pcm: bytes) -> None:
        if not pcm:
            return
        utterance = s.vad.feed(pcm)
        if utterance is None:
            return
        if self.stt is None:
            return
        async with s.stt_lock:   # one transcription at a time per session
            t0 = time.time()
            try:
                text, conf = await self.stt.transcribe(utterance)
            except Exception as e:  # noqa: BLE001
                logger.exception("[%s] stt failed", s.id)
                await self._send(s, {"type": "error", "message": f"stt failed: {e}"})
                return
        if text:
            logger.info("[%s] transcript (%.0f ms): %s", s.id, (time.time() - t0) * 1000, text[:80])
            await self._send(s, {"type": "transcript", "text": text, "is_final": True,
                                 "confidence": round(conf, 3)})

    # ---- util -------------------------------------------------------------
    async def _send(self, s: Session, msg: dict[str, Any]) -> None:
        if s.ws.closed:
            return
        try:
            await s.ws.send_str(json.dumps(msg))
        except Exception as e:  # noqa: BLE001
            logger.warning("[%s] send failed: %s", s.id, e)


def create_app() -> web.Application:
    server = VoiceServer()
    app = web.Application()
    app["server"] = server
    app.router.add_get("/health", server.health)
    app.router.add_get("/ws", server.websocket)
    app.router.add_get("/", server.root)
    return app


if __name__ == "__main__":
    host = os.environ.get("VOICE_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", os.environ.get("VOICE_PORT", "8765")))
    logger.info("starting voice server on %s:%d  (ws: /ws, health: /health)", host, port)
    web.run_app(create_app(), host=host, port=port, print=None)
