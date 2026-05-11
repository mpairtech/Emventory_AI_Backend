#!/usr/bin/env python3
"""Emit a bash script on stdout for `ssh ... bash -se` (used by GitHub Actions deploy).

Reads from the environment:
  REMOTE_DEPLOY_PATH — directory on the server (docker-compose.prod.yml lives here)
  IMAGE — full image ref to deploy
  GHCR_USER, GHCR_TOKEN — registry login

All values are shell-quoted for safe use with arbitrary PAT/path characters.
"""
from __future__ import annotations

import os
import shlex
import sys


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
        "{ " + login + "; } || remote_fail \"docker login failed - check GHCR_USER / GHCR_TOKEN (PAT needs read:packages)\"",
        "{ " + deploy + "; } || remote_fail \"deploy_blue_green.sh exited with error - see lines above on the server\"",
    ]
    sys.stdout.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
