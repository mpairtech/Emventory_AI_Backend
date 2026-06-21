#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-.env}"
IMAGE="${IMAGE:-}"
ACTIVE_FILE="${ACTIVE_FILE:-.active_color}"

if [[ -z "${IMAGE}" ]]; then
  echo "ERROR: IMAGE env var is required (e.g. ghcr.io/org/repo/emventory-ai-backend:stage)" >&2
  exit 1
fi

if [[ ! -f "${COMPOSE_FILE}" ]]; then
  echo "ERROR: ${COMPOSE_FILE} not found in $(pwd)" >&2
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "ERROR: ${ENV_FILE} not found in $(pwd)" >&2
  exit 1
fi

# Basic env validation (fail fast on missing critical vars)
required_vars=(API_SECRET DB_HOST DB_PORT DB_NAME DB_USER DB_PASSWORD)
for v in "${required_vars[@]}"; do
  if ! grep -Eq "^${v}=" "${ENV_FILE}"; then
    echo "ERROR: ${ENV_FILE} missing ${v}=..." >&2
    exit 1
  fi
done

provider="$(grep -E '^ACTIVE_PROVIDER=' "${ENV_FILE}" | tail -1 | cut -d= -f2- | tr -d '\r\n' || true)"
provider="${provider:-openai}"
provider="${provider,,}"
case "${provider}" in
  gemini)
    llm_var="GEMINI_API_KEY"
    ;;
  openai|*)
    llm_var="OPENAI_API_KEY"
    ;;
esac
if ! grep -Eq "^${llm_var}=" "${ENV_FILE}"; then
  echo "ERROR: ${ENV_FILE} missing ${llm_var}=... (required when ACTIVE_PROVIDER=${provider})" >&2
  exit 1
fi

echo "Validating compose file..."
IMAGE="${IMAGE}" ENV_FILE="${ENV_FILE}" docker compose -f "${COMPOSE_FILE}" config >/dev/null

ACTIVE="blue"
if [[ -f "${ACTIVE_FILE}" ]]; then
  ACTIVE="$(cat "${ACTIVE_FILE}" | tr -d '\r\n' | tr '[:upper:]' '[:lower:]')"
fi
if [[ "${ACTIVE}" != "blue" && "${ACTIVE}" != "green" ]]; then
  ACTIVE="blue"
fi
NEW="green"
if [[ "${ACTIVE}" == "green" ]]; then
  NEW="blue"
fi

echo "Active=${ACTIVE}, deploying NEW=${NEW}"

echo "Starting nginx (database is external via .env DB_*)..."
compose_up=(docker compose -f "${COMPOSE_FILE}")
if grep -Eq '^DB_HOST=postgres$' "${ENV_FILE}"; then
  echo "DB_HOST=postgres — also starting bundled postgres (profile local-db)..."
  compose_up+=(--profile local-db)
  IMAGE="${IMAGE}" ENV_FILE="${ENV_FILE}" "${compose_up[@]}" up -d postgres nginx
else
  IMAGE="${IMAGE}" ENV_FILE="${ENV_FILE}" "${compose_up[@]}" up -d nginx
fi

echo "Pulling image ${IMAGE}..."
IMAGE="${IMAGE}" ENV_FILE="${ENV_FILE}" docker compose -f "${COMPOSE_FILE}" pull "app_${NEW}"

echo "Running DB init (safe/no-op if already initialized)..."
IMAGE="${IMAGE}" ENV_FILE="${ENV_FILE}" docker compose -f "${COMPOSE_FILE}" run --rm "app_${NEW}" python -m scripts.init_db || true

echo "Starting new app app_${NEW}..."
IMAGE="${IMAGE}" ENV_FILE="${ENV_FILE}" docker compose -f "${COMPOSE_FILE}" up -d --no-deps "app_${NEW}"

cid="$(docker compose -f "${COMPOSE_FILE}" ps -q "app_${NEW}")"
if [[ -z "${cid}" ]]; then
  echo "ERROR: could not find container id for app_${NEW}" >&2
  exit 1
fi

echo "Waiting for container health..."
deadline=$((SECONDS + 120))
while true; do
  status="$(docker inspect --format='{{.State.Health.Status}}' "${cid}" 2>/dev/null || echo "unknown")"
  if [[ "${status}" == "healthy" ]]; then
    break
  fi
  if [[ "${status}" == "unhealthy" ]]; then
    echo "ERROR: app_${NEW} became unhealthy. Rolling back (keeping ${ACTIVE})." >&2
    IMAGE="${IMAGE}" ENV_FILE="${ENV_FILE}" docker compose -f "${COMPOSE_FILE}" logs --no-color --tail=200 "app_${NEW}" || true
    IMAGE="${IMAGE}" ENV_FILE="${ENV_FILE}" docker compose -f "${COMPOSE_FILE}" rm -sf "app_${NEW}" || true
    exit 1
  fi
  if (( SECONDS > deadline )); then
    echo "ERROR: timeout waiting for app_${NEW} to become healthy. Rolling back (keeping ${ACTIVE})." >&2
    IMAGE="${IMAGE}" ENV_FILE="${ENV_FILE}" docker compose -f "${COMPOSE_FILE}" logs --no-color --tail=200 "app_${NEW}" || true
    IMAGE="${IMAGE}" ENV_FILE="${ENV_FILE}" docker compose -f "${COMPOSE_FILE}" rm -sf "app_${NEW}" || true
    exit 1
  fi
  sleep 3
done

echo "Switching nginx upstream to ${NEW}..."
mkdir -p ./nginx/conf.d
cat > ./nginx/conf.d/upstream.conf <<EOF
upstream backend {
  server app_${NEW}:5000;
}
EOF

IMAGE="${IMAGE}" ENV_FILE="${ENV_FILE}" docker compose -f "${COMPOSE_FILE}" exec -T nginx nginx -s reload

echo "${NEW}" > "${ACTIVE_FILE}"

echo "Stopping old app app_${ACTIVE}..."
IMAGE="${IMAGE}" ENV_FILE="${ENV_FILE}" docker compose -f "${COMPOSE_FILE}" rm -sf "app_${ACTIVE}" || true

echo "Deploy complete. Active=${NEW}"

