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
    LOG_LEVEL: str = "INFO"

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

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"


settings = Settings()
