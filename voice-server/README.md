# voice-server

STT + TTS over one WebSocket for the VoicePlex backend. Claude (in the backend) is the brain; this
process only converts audio ⇄ text. Protocol: [PROTOCOL.md](PROTOCOL.md).

> This directory used to be called `personaplex/` and contained six different servers, most of which
> tried to use NVIDIA PersonaPlex-7B as a TTS engine. PersonaPlex is a speech-to-speech model and cannot
> be used that way; see `ARCHITECTURE.md` at the repo root for the reasoning and the migration path.

## Run locally (no GPU)

```bash
cd voice-server
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
sudo apt-get install -y ffmpeg          # macOS: brew install ffmpeg
python voice_server.py                  # ws://localhost:8765/ws
curl localhost:8765/health
```

Then in the dashboard: Settings → Voice server URL → `ws://localhost:8765/ws` → Test connection.

## Docker / RunPod / any VM

```bash
docker build -t voiceplex/voice-server .
docker run -p 8765:8765 voiceplex/voice-server
```
On RunPod expose HTTP port 8765; the public URL is `wss://<pod-id>-8765.proxy.runpod.net/ws`.
A GPU makes STT faster (`faster-whisper` auto-detects CUDA) but is not required for `base.en`.

## Environment

| Var | Default | Meaning |
|---|---|---|
| `PORT` / `VOICE_PORT` | 8765 | listen port |
| `VOICE_TTS_BACKEND` | `auto` | `edge` (needs network + ffmpeg) or `tone` (placeholder) |
| `VOICE_STT_BACKEND` | `auto` | `faster_whisper`, `whisper`, `none` |
| `VOICE_STT_MODEL` | `base.en` | whisper model size (`tiny.en` … `large-v3`) |
| `VOICE_VAD_THRESHOLD` | 400 | end-of-utterance energy threshold |
| `VOICE_LOG_LEVEL` | INFO | |

## Swapping backends

`voice_server.py` defines `TTSBackend` / `STTBackend` protocols. To add ElevenLabs, Cartesia,
Deepgram, etc., implement one class with `synthesize()` / `transcribe()` and register it in
`build_tts()` / `build_stt()`. Nothing in the backend changes.
