# AI Search Backend (FastAPI + pgvector)
FROM python:3.11-slim

WORKDIR /app

# Install system deps for psycopg2/pgvector
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
COPY requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY app/ ./app/
COPY scripts/ ./scripts/

# Default: run API
ENV PYTHONUNBUFFERED=1
EXPOSE 5000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5000"]
