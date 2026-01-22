from pydantic_settings import BaseSettings
from dotenv import load_dotenv
import os

load_dotenv()  # Load .env

class Settings(BaseSettings):
    DB_HOST: str
    DB_PORT: str
    DB_NAME: str
    DB_USER: str
    DB_PASSWORD: str
    OPENAI_API_KEY: str
    #GEMINI_API_KEY: str

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

settings = Settings()
