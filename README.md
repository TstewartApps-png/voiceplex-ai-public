# VoicePlex AI

AI phone agents for small businesses: a receptionist, scheduler, reminder caller or lead
qualifier that answers a Twilio number, talks to callers in real time and can book
appointments, take messages, send confirmations and transfer calls.

| Part | Tech | Folder |
|---|---|---|
| API | Python 3.11 · FastAPI · MongoDB (Motor) · Claude (Anthropic) · Twilio · Stripe | `backend/` |
| Dashboard | Next.js 14 · TypeScript · Tailwind · shadcn/ui | `frontend/` |
| Voice server | Python · aiohttp · faster-whisper (STT) · edge-tts (TTS) | `voice-server/` |

Docs: [ARCHITECTURE.md](ARCHITECTURE.md) (how a call flows, why the pieces are what they are) ·
[STATUS.md](STATUS.md) (what is verified working, what is not) ·
[voice-server/PROTOCOL.md](voice-server/PROTOCOL.md).

---

## Run it locally

Prerequisites: Python 3.11+, Node 18+, MongoDB 7 (local or Atlas), `ffmpeg`.

```bash
cp .env.example .env          # set SECRET_KEY, ENCRYPTION_KEY, MONGODB_URI (required)

# 1. backend  -> http://localhost:8000  (Swagger: /docs when DEBUG=true)
cd backend
python -m venv venv && . venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
python seed_database.py                         # demo user: demo@example.com / Test123!
uvicorn app.main:app --reload --port 8000

# 2. frontend -> http://localhost:3000
cd ../frontend
npm install
echo NEXT_PUBLIC_API_URL=http://localhost:8000 > .env.local
npm run dev

# 3. voice server -> ws://localhost:8765/ws  (optional until you test voice)
cd ../voice-server
pip install -r requirements.txt
python voice_server.py
```

Or everything in containers: `docker compose up --build`.

`npm run dev` at the repo root starts all three with `concurrently`; `npm test` runs the backend tests.

## Tests

```bash
cd backend && pytest -q          # ~53 tests, in-memory MongoDB, no services needed
cd frontend && npx tsc --noEmit && npm run build
```

## Connecting the real services

Everything below is configured **per tenant in the dashboard** (Settings page) and stored
encrypted. Environment variables with the same meaning act as platform-wide fallbacks.

| Service | Where | What it does |
|---|---|---|
| **Anthropic** | Settings → Anthropic | Claude drives every conversation and the "generate prompt" copilot. |
| **Voice server** | Settings → Voice server URL | Speech-to-text / text-to-speech for calls and voice previews. `ws://localhost:8765/ws` locally, `wss://<pod>-8765.proxy.runpod.net/ws` on RunPod. "Test connection" must succeed before previews work. |
| **Twilio** | Settings → Twilio | Account SID, auth token, *a number you already own*, and the agent that answers it. "Test connection" also points that number's voice webhook at `BACKEND_URL/api/v1/webhooks/twilio/voice`. For local testing expose the backend with `ngrok http 8000` and set `BACKEND_URL` to the ngrok URL **before** testing. Additional numbers can be attached to a company on the Companies page. |
| **Google / Microsoft** | Integrations page (per company) | Calendar availability/booking and email confirmations used by agent tools. Needs `GOOGLE_*` / `MICROSOFT_*` OAuth app credentials in `.env`; redirect URIs are listed in `.env.example`. |
| **Stripe** | `.env` only | Billing is intentionally deferred; endpoints exist but are not part of the supported flow. |

Security notes: Twilio webhooks are signature-verified (disabled only when `DEBUG=true` **and**
no signature is sent); the media-stream WebSocket requires a per-call token; never commit `.env`.

## Layout

```
backend/app/
  api/v1/        routers: auth companies agents calls voice integrations billing settings knowledge
  webhooks/      twilio (signed) · stripe
  services/      auth company agent call credentials · ai/ (claude, conversation, tools/) ·
                 voice/ (orchestrator, voice-server client, twilio) · billing/ · integrations/
  models/        Pydantic schemas = MongoDB document shapes
frontend/src/app/(auth)  dashboard/{agents,calls,companies,integrations,settings,billing,analytics}
voice-server/    voice_server.py · PROTOCOL.md
```

## License

License: MIT
