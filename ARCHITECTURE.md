# Architecture

## Call flow (inbound)

```
caller ──PSTN──▶ Twilio number
                   │ POST /api/v1/webhooks/twilio/voice   (X-Twilio-Signature verified)
                   ▼
            backend resolves number → tenant → active agent   (AgentService.get_agent_by_phone)
            creates `calls` doc + in-memory CallSession (with a random stream_token)
            returns TwiML  <Connect><Stream url=wss://…/api/v1/voice/stream/{session}>
                                       <Parameter name="token" value=…/>
                   │ Twilio opens the media-stream WebSocket (μ-law 8 kHz)
                   ▼
   ┌─────────────── CallOrchestrator (backend) ────────────────┐
   │  "start" event must carry the stream token, else close    │
   │  μ-law 8k → PCM 24k ──▶ voice-server {"type":"audio"}     │
   │  ◀── {"type":"transcript"}  (utterance from STT)          │
   │  ConversationManager → Claude (tenant's key) + tools      │
   │       tools: calendar (Google/MS), email, transfer,       │
   │              take_message, knowledge search, end_call     │
   │  reply text ──▶ voice-server {"type":"speak"}             │
   │  ◀── {"type":"audio"} frames → PCM 8k μ-law → Twilio      │
   │  on hang-up: finalize call, bill minutes, agent analytics │
   └───────────────────────────────────────────────────────────┘
```

Voice preview in the agent editor uses the same voice server with a one-shot `{"type":"tts"}`.

## Components

| Component | Responsibility | Notes |
|---|---|---|
| `webhooks/twilio_webhooks.py` | Twilio entry points | Signature check tries the owning tenant's token (looked up from `To`/`CallSid`) then the platform token. |
| `services/voice/call_orchestrator.py` | Session state machine, audio resampling, turn taking | Sessions are in-process memory → run **one** backend replica, or move sessions to Redis before scaling out. |
| `services/voice/personaplex_client.py` | WebSocket client to the voice server | Name is historical; see below. |
| `services/ai/conversation.py` + `tools/` | Claude prompt, history window, tool execution | Tools are selected from `agent.capabilities`. Calendar tools fall back to **mock availability** when no calendar is connected — disable `schedule_appointments` on agents without a calendar. |
| `services/credentials.py` | Per-tenant credentials (Settings) with env fallback | The only place secrets are resolved. |
| `voice-server/` | STT + TTS over one WebSocket | Stateless; deploy anywhere with `ffmpeg` (GPU optional). |

## Data model (MongoDB)

`users` (subscription, settings) · `settings` (per-user encrypted Twilio/Anthropic creds, voice URL, default agent) ·
`companies` (phone_numbers[], OAuth tokens, branding, hours) · `agents` (voice, persona, capabilities,
calendar/transfer/conversation settings, knowledge_base[], analytics) · `calls` (transcript[], outcome,
appointment/message/lead, billable_minutes) · `sessions` (refresh tokens, TTL) · `usage_records`.

Foreign keys (`user_id`, `company_id`, `agent_id`) are stored as **strings** everywhere; `_id` is an
`ObjectId`. Keep it that way (the seed script and services enforce it).

## Why not NVIDIA PersonaPlex?

The original plan used NVIDIA PersonaPlex-7B for "TTS/STT with <200 ms latency". PersonaPlex is a
**full-duplex speech-to-speech model** (Moshi architecture): it listens and generates its own spoken
answer from a persona prompt. It has no API to "say this text" or "transcribe this audio", so it cannot
sit behind Claude as a TTS/STT engine, and the previous servers that tried (`model.generate_speech`,
`--response-text`, …) were calling functions that do not exist.

Two coherent designs exist:

* **A — Claude is the brain (current).** STT → Claude + tools → TTS. Deterministic booking/transfer/
  messages, any TTS vendor, no GPU required. Turn latency ≈ 0.7–1.5 s. This is what the codebase
  implements end to end.
* **B — PersonaPlex is the brain.** Twilio ↔ backend ↔ `moshi.server` (binary Opus frames). Very low
  latency and natural barge-in, but Claude tool-calling is gone; booking/transfer would need a text
  side-channel and new prompting. Needs a 24 GB GPU per handful of calls.

Swapping TTS/STT vendors in design A is a ~50-line backend class in `voice-server/voice_server.py`
(ElevenLabs, Cartesia, Deepgram, …). Moving to design B is a rewrite of the orchestrator and tools.

## Scaling / production checklist

* One backend replica until sessions live in Redis (orchestrator `_sessions`).
* `BACKEND_URL` must be the public HTTPS URL Twilio calls (signature validation depends on it).
* Set `APP_ENV=production`, `DEBUG=false` (disables docs, signature bypass, detailed 500s).
* Tokens are in `localStorage` on the frontend — move to httpOnly cookies before handling real PII.
* Celery workers referenced by old docs do not exist; outbound/reminder calls are not scheduled yet.
