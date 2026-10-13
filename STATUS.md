# Status

Rule for this file: a ✅ needs a command or test next to it that anyone can re-run. Claims without
evidence go under "unverified".

## Verified ✅ (`cd backend && pytest -q` — 53 tests, in-memory MongoDB)

| Area | Evidence |
|---|---|
| Register / login / refresh / `me`, duplicate-email 409, weak password 422 | `tests/test_auth.py` |
| Company + agent CRUD, activate/pause | exercised by `tests/test_phone_routing.py`, `tests/test_seed.py` |
| Twilio webhooks reject missing/invalid signatures; accept valid ones for `BACKEND_URL`, `X-Forwarded-*`, and the tenant's own token | `tests/test_security.py` |
| Inbound call → tenant number → agent (default agent, single-active fallback, ambiguity → polite hang-up, paused agent ignored, company assignment wins) → call record → TwiML with stream token | `tests/test_phone_routing.py` |
| Attach a Twilio number to a company (verified against the account, webhooks configured, real SID stored) | `tests/test_phone_routing.py` (Twilio SDK mocked) |
| Settings → Twilio "Test connection" configures the number's webhook | `tests/test_phone_routing.py` |
| Credentials: Settings values win over env for Claude / voice URL / Twilio | `tests/test_credentials.py` |
| `/voice/sessions*` require auth and are tenant-scoped | `tests/test_security.py` |
| `/knowledge/scrape` blocks loopback / private / metadata hosts and redirects to them | `tests/test_security.py` |
| Call end bills ceil(minutes) to the user, writes `usage_records`, increments agent analytics; unanswered calls not billed | `tests/test_usage_rollup.py` |
| `GET /billing/usage` works (was a `TypeError`) | `tests/test_usage_rollup.py` |
| Calendar/email tools and Google/Microsoft services reach the DB (13 `await get_database()` TypeErrors fixed) | `tests/test_tools_db_access.py` |
| OAuth: `company_id` contract, tenant scoping, NOT_CONFIGURED 503, callbacks redirect to `/dashboard/integrations` | `tests/test_integrations_oauth.py` |
| Seed script data visible through the API, idempotent | `tests/test_seed.py` |
| Frontend type-checks and builds | `cd frontend && npx tsc --noEmit && npm run build` |
| Voice server protocol: ping/config/tts/speak (streamed, interruptible)/audio/interrupt/end/error | manual run with placeholder backends (see below) |

## Implemented but needs a live service to verify ⚠️

* **Voice server with real backends** — `edge-tts` and `faster-whisper` are wired but both need
  internet (Microsoft endpoint / model download). Run `python voice_server.py`, hit `/health`,
  and confirm `"tts": "edge-tts"`, `"stt": "faster-whisper"`.
* **A complete phone call** — needs Twilio + public `BACKEND_URL` + voice server + Anthropic key.
  Expected path is documented in `ARCHITECTURE.md`; the orchestrator's resampling/turn logic has
  not been exercised against real Twilio audio in this repo.
* **Google / Microsoft OAuth round-trip** — needs OAuth app credentials.
* **Calendar / email tools against real accounts** — code paths exist; only mock fallbacks run in tests.
* **Outbound calls** — `POST /calls/outbound` creates the record but does not dial yet (TODO in
  `api/v1/calls.py`; use `TwilioHandler.for_user(...).initiate_outbound_call`).

## Known gaps / not started ❌

* Billing / Stripe: intentionally deferred. Endpoints exist; not part of the supported flow.
* Celery workers (reminders, scheduled outbound): referenced historically, not implemented.
* Sessions are in-process → single backend replica.
* Agent wizard page (`frontend/src/app/dashboard/agents/new/page.tsx`) is 2.4k lines in one
  component; works, but should be split per step before more features land.
* `Persona.voice_prompt_audio` / `knowledge_base[].embedding` are returned on every agent list
  response (payload bloat).
* Frontend auth tokens in `localStorage`.
