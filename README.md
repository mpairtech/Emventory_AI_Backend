# Emventory AI Backend (FastAPI + pgvector)

This repo hosts the AI search backend:
- FastAPI API (`/api/v1`)
- Postgres + `pgvector` for semantic search
- Gemini/OpenAI for embeddings + RAG generation

## Project structure

- `app/`: application code (API, core, db, modules)
  - `app/main.py`: FastAPI entrypoint
  - `app/api/`: routers + schemas
  - `app/core/`: settings, llm clients, vector store helpers, exceptions
  - `app/db/`: SQLAlchemy engine + models
  - `app/modules/`: domain modules (e.g. `search`)
- `scripts/`: operational scripts (kept in git)
- `docs/`: documentation (kept in git)

## Local run

1) Create `.env` (copy from `.env.example`)

Optional: you can set `APP_ENV=local` (or `prod`) to load YAML defaults from `config/`.

2) Install dependencies:

```bash
pip install -r requirements.txt
```

For full (includes heavy ML libs):

```bash
pip install -r requirements-full.txt
```

2) Start services:

```bash
docker compose up --build
```

API should be available at `http://localhost:5000` (Swagger: `/docs`).

## One-off DB init (optional)

The app auto-initializes the DB on startup, but you can also run:

```bash
python -m scripts.init_db
```

