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

1. Create `.env` (copy from `.env.example`)

Optional: you can set `APP_ENV=local` (or `prod`) to load YAML defaults from `config/`.

2. Install dependencies:

```bash
pip install -r requirements.txt
```

For full (includes heavy ML libs):

```bash
pip install -r requirements-full.txt
```

2. Start services:

```bash
docker compose up --build
```

API should be available at `http://localhost:5000` (Swagger: `/docs`).

## CI/CD (GitHub Actions)

This repo includes:

- **Single workflow**: `.github/workflows/ci-cd.yml`
  - CI runs on PRs and on pushes to `main/master/stage`
  - Builds & pushes image to GHCR on push (with SBOM/provenance attestations when the registry supports them)
  - Trivy scans the pushed image on push
  - Auto-deploys staging on push to `stage` (can be turned off with a repo variable; see below)
  - Production deploy is manual via **workflow dispatch** (optional `image_tag`; default image is `:main`)

### Security notes

- **Permissions**: the workflow defaults to `contents: read`; publish/deploy jobs request only what they need (`packages: write`, `id-token: write` for attestations, `actions: write` for BuildKit GHA cache).
- **Fork PRs**: pull requests from forks run smoke + Docker build with a read-only token; **repository Actions secrets are not exposed to fork workflows** (GitHub default). Treat PR CI as “untrusted code until merged.”
- **Concurrency**: new pushes to the same branch **queue** (they do not cancel an in-flight deploy). New commits on a PR **cancel** the previous PR run to save minutes.
- **GitHub Environments**: deploy jobs use `environment: staging` and `environment: production`. In repo **Settings → Environments** you can add **required reviewers** or **wait timers** before SSH deploy runs.
- **Dependabot**: `.github/dependabot.yml` bumps GitHub Actions and the root Dockerfile on a weekly schedule.

### Required GitHub Secrets (for deploy)

Set these in the repo **Settings → Secrets and variables → Actions**:

**Shared (staging + production pulls from GHCR)**

- **`GHCR_USER`**: GHCR username (often your GitHub username)
- **`GHCR_TOKEN`**: a GitHub PAT with `read:packages` (and `repo` if needed for private repos)

**Staging** — used when the workflow auto-deploys on push to the `stage` branch:

- **`STAGE_DEPLOY_HOST`**: staging server IP / hostname
- **`STAGE_DEPLOY_USER`**: SSH user (e.g. `ubuntu`)
- **`STAGE_DEPLOY_SSH_KEY`**: private key for that user (ed25519 recommended)
- **`STAGE_DEPLOY_PATH`**: path on the staging host containing `docker-compose.prod.yml` and `.env`

**Recommended staging environment secrets** (upserted into server `.env` on each deploy):

- **`GEMINI_API_KEY`**: required when `ACTIVE_PROVIDER=gemini` in server `.env`
- **`OPENAI_API_KEY`**: required when `ACTIVE_PROVIDER=openai`
- **`API_SECRET`**: optional; only set if you want CI to overwrite the server value

**Optional repo variable (Actions → Variables):**

- **`STAGING_DEPLOY_ACTIVE`**: leave unset or set to `true` while you use staging. Set to **`false`** when you have torn down the staging host or path so pushes to `stage` still build/push the image but **do not** run the SSH deploy job (avoids failed deploys after you delete the test server).

**Production** — used by the manual *Deploy to Production* workflow dispatch:

- **`DEPLOY_HOST`**: production server IP / hostname
- **`DEPLOY_USER`**: SSH user
- **`DEPLOY_SSH_KEY`**: private key for that user
- **`DEPLOY_PATH`**: path on the production host containing `docker-compose.prod.yml` and `.env`

If staging and production run on the same host with the same deploy directory, you may set the four `STAGE_DEPLOY_*` values equal to the four `DEPLOY_*` values (still configure both sets so each job has what it needs).

### Short-lived (temporary) staging

For a limited test window (e.g. a few days on a throwaway VM or a temp directory):

1. Point **`STAGE_DEPLOY_*`** at that host/path and keep **`STAGING_DEPLOY_ACTIVE`** unset or `true`.
2. Push to **`stage`** to deploy and test as usual.
3. When finished: stop/remove containers on the host (`docker compose -f docker-compose.prod.yml down` in `STAGE_DEPLOY_PATH`), delete the VM or folder if you no longer need it.
4. Set **`STAGING_DEPLOY_ACTIVE`** to **`false`** so future `stage` pushes still run CI and publish the image but skip the staging SSH step until you spin up staging again.

## Production run (Docker Compose)

On your KVM host, keep a deployment folder (example: `/opt/emventory-ai-backend`) with:

- `docker-compose.prod.yml` (from this repo)
- `.env` (production secrets; start from `.env.example`)

Set **Neon** (or any external Postgres) in `.env`: `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`. `DB_SSL=auto` enables SSL for `*.neon.tech` hosts.

Then run (app + nginx only; no bundled Postgres):

```bash
ENV_FILE=.env docker compose -f docker-compose.prod.yml up -d
```

Optional bundled Postgres for staging (`DB_HOST=postgres` in `.env`):

```bash
ENV_FILE=.env docker compose -f docker-compose.prod.yml --profile local-db up -d
```

## One-off DB init (optional)

The app auto-initializes the DB on startup, but you can also run:

```bash
python -m scripts.init_db
```
