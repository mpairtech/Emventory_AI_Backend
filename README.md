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

## CI/CD (GitHub Actions)

This repo includes:

- **Single workflow**: `.github/workflows/ci-cd.yml`
  - CI runs on PRs and on pushes to `main/master/stage`
  - Builds & pushes image to GHCR on push
  - Auto-deploys staging on push to `stage`
  - Production deploy is manual via workflow dispatch

### Required GitHub Secrets (for deploy)

Set these secrets in your GitHub repo settings:

- **`DEPLOY_HOST`**: server IP / hostname
- **`DEPLOY_USER`**: SSH user (e.g. `ubuntu`)
- **`DEPLOY_SSH_KEY`**: private key for that user (ed25519 recommended)
- **`DEPLOY_PATH`**: path on server containing `docker-compose.prod.yml` and `.env.production`
- **`GHCR_USER`**: GHCR username (often your GitHub username)
- **`GHCR_TOKEN`**: a GitHub PAT with `read:packages` (and `repo` if needed for private repos)

For **staging auto-deploy** (stage branch), set these secrets too:

- **`STAGE_DEPLOY_HOST`**
- **`STAGE_DEPLOY_USER`**
- **`STAGE_DEPLOY_SSH_KEY`**
- **`STAGE_DEPLOY_PATH`**

## Production run (Docker Compose)

On your KVM host, keep a deployment folder (example: `/opt/emventory-ai-backend`) with:

- `docker-compose.prod.yml` (from this repo)
- `.env.production` (your production env file; start from `.env.example`)

Then run:

```bash
ENV_FILE=.env.production docker compose -f docker-compose.prod.yml up -d
```

## One-off DB init (optional)

The app auto-initializes the DB on startup, but you can also run:

```bash
python -m scripts.init_db
```

