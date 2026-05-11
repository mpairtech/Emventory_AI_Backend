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
        f"cd {shlex.quote(path)}",
        "test -f docker-compose.prod.yml",
        "test -f .env",
        "test -x scripts/deploy_blue_green.sh",
        login,
        deploy,
    ]
    sys.stdout.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
