from pydantic_settings import BaseSettings
from pydantic import field_validator
from dotenv import load_dotenv

load_dotenv()

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

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"


settings = Settings()
