#!/usr/bin/env bash
# Prepare ~/.ssh for GitHub Actions deploy (private key + optional known_hosts).
#
# Environment:
#   DEPLOY_HOST      — hostname or IP only (no user@, no ssh://)
#   SSH_PRIVATE_KEY  — full private key PEM (ed25519 recommended)
set -euo pipefail

host="${DEPLOY_HOST:-}"
key="${SSH_PRIVATE_KEY:-}"

if [[ -z "${host}" ]]; then
  echo "::error::DEPLOY_HOST is empty" >&2
  exit 1
fi
if [[ -z "${key}" ]]; then
  echo "::error::SSH_PRIVATE_KEY is empty" >&2
  exit 1
fi

host="$(printf '%s' "${host}" | tr -d '\r\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"

if [[ "${host}" == *@* ]]; then
  echo "::error::DEPLOY_HOST must be hostname or IP only (no user@). Use STAGE_DEPLOY_USER / DEPLOY_USER for the SSH user." >&2
  exit 1
fi
if [[ "${host}" == *"://"* ]]; then
  echo "::error::DEPLOY_HOST must not include a URL scheme (use bare hostname or IP)" >&2
  exit 1
fi

mkdir -m 700 -p ~/.ssh
printf '%s' "${key}" | tr -d '\r' > ~/.ssh/id_ed25519
printf '\n' >> ~/.ssh/id_ed25519
chmod 600 ~/.ssh/id_ed25519

if ! ssh-keygen -y -f ~/.ssh/id_ed25519 >/dev/null 2>&1; then
  echo "::error::SSH private key is invalid. Paste the full key including -----BEGIN ... PRIVATE KEY----- lines into STAGE_DEPLOY_SSH_KEY / DEPLOY_SSH_KEY." >&2
  exit 1
fi

touch ~/.ssh/known_hosts
chmod 600 ~/.ssh/known_hosts
if ssh-keyscan -T 15 -H "${host}" >> ~/.ssh/known_hosts 2>/dev/null; then
  echo "Added ${host} host key(s) to known_hosts"
else
  echo "::warning::ssh-keyscan could not reach ${host}:22 (host down, firewall, or wrong STAGE_DEPLOY_HOST). Deploy will still try StrictHostKeyChecking=accept-new."
fi
