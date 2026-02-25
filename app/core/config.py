from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

# Load `.env` first (highest priority after real env vars)
load_dotenv()


def _set_env_default(key: str, value) -> None:
    """
    Set an env var only if it doesn't already exist.
    This allows YAML config to provide *defaults* while `.env`/real env override.
    """
    if value is None:
        return
    s = str(value).strip()
    if not s:
        return
    os.environ.setdefault(key, s)


def _apply_yaml_defaults() -> None:
    """
    Optional YAML config support.

    - If `APP_CONFIG_FILE` (or `CONFIG_FILE`) is set, load that file.
    - Else if `APP_ENV` is `local` or `prod`, load `config/{APP_ENV}.yaml`.

    YAML values are applied as *defaults* (won't override existing env vars).
    """
    config_file = (os.getenv("APP_CONFIG_FILE") or os.getenv("CONFIG_FILE") or "").strip()
    app_env = (os.getenv("APP_ENV") or "").strip().lower()

    repo_root = Path(__file__).resolve().parents[2]
    if not config_file and app_env in {"local", "prod"}:
        config_file = str(repo_root / "config" / f"{app_env}.yaml")

    if not config_file:
        return

    config_path = Path(config_file)
    if not config_path.is_absolute():
        config_path = repo_root / config_path

    if not config_path.exists():
        logger.warning("Config file not found: %s", config_path)
        return

    try:
        raw = config_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw) or {}
    except Exception as e:
        logger.warning("Failed to load config YAML (%s): %s", config_path, e)
        return

    app_cfg = data.get("app") or {}
    db_cfg = data.get("db") or {}

    # app
    _set_env_default("LOG_LEVEL", app_cfg.get("log_level"))
    _set_env_default("ACTIVE_PROVIDER", app_cfg.get("active_provider"))

    # db
    _set_env_default("DB_HOST", db_cfg.get("host"))
    _set_env_default("DB_PORT", db_cfg.get("port"))
    _set_env_default("DB_NAME", db_cfg.get("name"))
    _set_env_default("DB_USER", db_cfg.get("user"))
    _set_env_default("DB_PASSWORD", db_cfg.get("password"))
    # redis
    _set_env_default("REDIS_HOST", redis_cfg.get("host"))
    _set_env_default("REDIS_PORT", redis_cfg.get("port"))
    _set_env_default("REDIS_DB", redis_cfg.get("db"))
    _set_env_default("REDIS_PASSWORD", redis_cfg.get("password"))


# Apply YAML defaults (lower priority than env + .env)
_apply_yaml_defaults()

# Embedding dimension must match DB model and Gemini text-embedding-004
EMBEDDING_DIM = 768


class Settings(BaseSettings):
    DB_HOST: str
    DB_PORT: str  # PostgreSQL port (usually 5432; use 5433 if postgres is mapped from Docker)
    DB_NAME: str
    DB_USER: str
    DB_PASSWORD: str
    GEMINI_API_KEY: str
    # Optional: OpenAI configuration for text generation / search
    OPENAI_API_KEY: str | None = None
    OPENAI_MODEL: str = "gpt-4.1-mini"
    # Active LLM provider: "gemini" or "openai". Defaults to "gemini" if not set.
    ACTIVE_PROVIDER: str = "gemini"
    LOG_LEVEL: str = "INFO"

    # Required: server-side secret to generate API keys from user input. Key = HMAC(API_SECRET, user_input).
    # Client must send X-Key-Input (e.g. org_id) and X-API-Key = HMAC(API_SECRET, X-Key-Input).
    API_SECRET: str

    # Redis Configuration
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str | None = None
    REDIS_ENABLED: bool = True  # Feature flag to enable/disable caching
    REDIS_TTL_RAG: int = 900  # 15 minutes for RAG responses
    REDIS_TTL_EMBEDDINGS: int = 3600  # 1 hour for embeddings
    REDIS_MAX_CONNECTIONS: int = 10
    REDIS_SOCKET_TIMEOUT: int = 5
    REDIS_SOCKET_CONNECT_TIMEOUT: int = 5

    SPEECH_MODEL_NAME: str = "openai/whisper-base"
    SPEECH_DEVICE: str = "cpu"  # "cpu" or "cuda" (for GPU)
    SPEECH_LANGUAGE_CODE: str = "en"  # ISO language code
    SPEECH_MAX_AUDIO_SIZE_MB: int = 10
    SPEECH_SUPPORTED_FORMATS: list[str] = ["wav", "mp3", "flac", "ogg", "webm", "m4a"]

   


    
    # Optional: Hugging Face token for private models (not needed for Whisper)
    HUGGINGFACE_TOKEN: str | None = None
    
    # Model caching
    SPEECH_MODEL_CACHE_DIR: str = "./models/cache"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @field_validator("DB_PORT")
    @classmethod
    def db_port_valid(cls, v: str) -> str:
        try:
            port = int(v)
            if not (1 <= port <= 65535):
                raise ValueError("DB_PORT must be between 1 and 65535")
        except ValueError as e:
            if "invalid literal" in str(e).lower():
                raise ValueError("DB_PORT must be a number")
            raise
        return v

    @field_validator("ACTIVE_PROVIDER")
    @classmethod
    def active_provider_valid(cls, v: str) -> str:
        v_lower = v.lower().strip()
        if v_lower not in ["gemini", "openai"]:
            raise ValueError("ACTIVE_PROVIDER must be either 'gemini' or 'openai'")
        return v_lower
    @field_validator("REDIS_PORT")
    @classmethod
    def redis_port_valid(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError("REDIS_PORT must be between 1 and 65535")
        return v
    
    @field_validator("REDIS_DB")
    @classmethod
    def redis_db_valid(cls, v: int) -> int:
        if not (0 <= v <= 15):
            raise ValueError("REDIS_DB must be between 0 and 15")
        return v

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
    @property
    def MAX_AUDIO_SIZE_BYTES(self) -> int:
        return self.SPEECH_MAX_AUDIO_SIZE_MB * 1024 * 1024


settings = Settings()
