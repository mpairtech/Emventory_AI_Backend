#!/usr/bin/env python3
"""Emit a bash script on stdout for `ssh ... bash -se` (used by GitHub Actions deploy).

Reads from the environment:
  REMOTE_DEPLOY_PATH — directory on the server (docker-compose.prod.yml lives here)
  IMAGE — full image ref to deploy
  GHCR_USER, GHCR_TOKEN — registry login

Optional (upserted into server .env before deploy when set):
  GEMINI_API_KEY, OPENAI_API_KEY, API_SECRET

All values are shell-quoted for safe use with arbitrary PAT/path characters.
"""
from __future__ import annotations

import json
import os
import shlex
import sys

# Keys synced from GitHub Actions secrets into the server .env on each deploy.
ENV_PATCH_KEYS = ("GEMINI_API_KEY", "OPENAI_API_KEY", "API_SECRET")


def env_patch_lines() -> list[str]:
    patches = {k: os.environ[k] for k in ENV_PATCH_KEYS if os.environ.get(k)}
    if not patches:
        return []
    return [
        "echo 'Updating .env keys from CI secrets (values not printed)...'",
        "python3 - <<'PY'",
        "import json, pathlib, re",
        f"patches = json.loads({json.dumps(json.dumps(patches))})",
        'path = pathlib.Path(".env")',
        "rows = path.read_text(encoding='utf-8').splitlines() if path.exists() else []",
        "out, seen = [], set()",
        "for line in rows:",
        "    m = re.match(r'^([A-Z_][A-Z0-9_]*)=', line)",
        "    if m and m.group(1) in patches:",
        "        k = m.group(1)",
        "        out.append(f'{k}={patches[k]}')",
        "        seen.add(k)",
        "    else:",
        "        out.append(line)",
        "for k, v in patches.items():",
        "    if k not in seen:",
        "        out.append(f'{k}={v}')",
        "path.write_text('\\n'.join(out) + ('\\n' if out else ''), encoding='utf-8')",
        "print('Patched:', ', '.join(sorted(patches)))",
        "PY",
    ]


def main() -> None:
    try:
        path = os.environ["REMOTE_DEPLOY_PATH"]
        image = os.environ["IMAGE"]
        user = os.environ["GHCR_USER"]
        token = os.environ["GHCR_TOKEN"]
    except KeyError as e:
        print(f"missing env: {e.args[0]}", file=sys.stderr)
        sys.exit(1)

    fmt = shlex.quote(r"%s\n")
    login = (
        f"printf {fmt} {shlex.quote(token)} | "
        f"docker login ghcr.io -u {shlex.quote(user)} --password-stdin"
    )
    deploy = (
        "IMAGE="
        + shlex.quote(image)
        + " ENV_FILE=.env COMPOSE_FILE=docker-compose.prod.yml "
        + "./scripts/deploy_blue_green.sh"
    )
    lines = [
        "set -euo pipefail",
        'remote_fail() { echo "::error::remote: $*" >&2; exit 1; }',
        f"cd {shlex.quote(path)} || remote_fail \"cd failed - fix REMOTE_DEPLOY_PATH / STAGE_DEPLOY_PATH or DEPLOY_PATH secret (no such dir or no permission)\"",
        "test -f docker-compose.prod.yml || remote_fail \"missing docker-compose.prod.yml - copy it from the repo into the deploy directory on the server\"",
        "test -f .env || remote_fail \"missing .env in deploy directory\"",
        "test -x scripts/deploy_blue_green.sh || remote_fail \"missing or non-executable scripts/deploy_blue_green.sh - clone/copy repo scripts into the deploy directory\"",
        *env_patch_lines(),
        "{ " + login + "; } || remote_fail \"docker login failed - check GHCR_USER / GHCR_TOKEN (PAT needs read:packages)\"",
        "{ " + deploy + "; } || remote_fail \"deploy_blue_green.sh exited with error - see lines above on the server\"",
    ]
    sys.stdout.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
