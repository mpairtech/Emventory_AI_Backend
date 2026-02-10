# Config folder

This folder contains **optional YAML config files** (`local.yaml`, `prod.yaml`).

The application loads configuration from **environment variables** via `app/core/config.py`
(`.env` is supported through `python-dotenv`).

Optionally, you can also load YAML **defaults**:
- Set `APP_ENV=local` → loads `config/local.yaml`
- Set `APP_ENV=prod` → loads `config/prod.yaml`
- Or set `APP_CONFIG_FILE=path/to/file.yaml`

YAML values are applied as *defaults only* (they will **not** override real env vars or `.env`).

Use `.env.example` at the repo root as the canonical reference.

