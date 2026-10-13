# Voice server WebSocket protocol

Single endpoint: `ws(s)://host:8765/ws` (`/` also accepts upgrades). Health: `GET /health`.
All frames are JSON text. Audio payloads are **16-bit signed LE PCM, mono, 24 000 Hz**, base64.

| Client → server | Server → client | Used by |
|---|---|---|
| `{"type":"ping"}` | `{"type":"pong","status":"connected"}` | Settings → Test connection |
| `{"type":"config","voice_id":"NATF0","speed":1.0,"sample_rate":24000,"text_prompt":"…"}` | `{"type":"ready","session_id":"s1"}` | preview + live calls (`text_prompt` is ignored; Claude owns the persona) |
| `{"type":"tts","text":"…","voice_id":"NATF0","speed":1.0}` | `{"type":"audio","audio":"<b64>","sample_rate":24000,"duration_ms":N,"is_final":true}` | `POST /voice/preview` |
| `{"type":"speak","text":"…"}` | `{"type":"speaking"}` → N × `{"type":"audio",…,"is_final":bool}` → `{"type":"stopped"}` | live call agent turn |
| `{"type":"audio","audio":"<b64 pcm>"}` or binary frame | `{"type":"transcript","text":"…","is_final":true,"confidence":0.93}` when an utterance ends | live call caller audio |
| `{"type":"interrupt"}` | `{"type":"stopped","reason":"interrupted"}` | barge-in |
| `{"type":"end"}` | socket closed | hang-up |
| `{"type":"list_voices"}` | `{"type":"voices","voices":[{"id","name","gender"}]}` | – |
| anything else | `{"type":"error","message":"…"}` | – |

On connect the server sends `{"type":"connected", "tts": "...", "stt": "..."}` — clients must ignore unknown
informational messages.

Utterance segmentation is energy-based: ≥250 ms of speech followed by ≥700 ms of silence, or 15 s max.
Tune with `VOICE_VAD_THRESHOLD` (RMS on int16 scale, default 400).
