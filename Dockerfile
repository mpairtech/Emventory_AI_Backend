# AI Search Backend (FastAPI + pgvector) — production image
FROM python:3.11-slim AS runtime

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System deps (psycopg2 needs libpq); upgrade first for Debian security fixes (e.g. libssh2)
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user
RUN useradd --create-home --shell /usr/sbin/nologin appuser

COPY requirements-prod.txt ./

# Build deps only for pip install, then removed (keeps final image small-ish)
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && pip install -r requirements-prod.txt \
    && apt-get purge -y --auto-remove gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY app/ ./app/
COPY scripts/ ./scripts/

EXPOSE 5000

# Simple container healthcheck (requires curl)
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
  CMD curl -fsS http://127.0.0.1:5000/healthz || exit 1

USER appuser

# Gunicorn is the recommended prod runner; configure workers via env.
ENV WEB_CONCURRENCY=2
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "-b", "0.0.0.0:5000", "--access-logfile", "-", "--error-logfile", "-", "app.main:app"]
