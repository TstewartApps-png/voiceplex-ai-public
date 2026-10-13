# backend

FastAPI API for VoicePlex. Setup, configuration and the list of routers live in the
[root README](../README.md); call flow and data model in [ARCHITECTURE.md](../ARCHITECTURE.md).

```bash
python -m venv venv && . venv/bin/activate
pip install -r requirements.txt
python seed_database.py          # demo data through the app's own services
uvicorn app.main:app --reload --port 8000
pytest -q                        # in-memory MongoDB, no services required
```

Lint/format: `ruff check app tests` · `black app tests` · `isort app tests`.
