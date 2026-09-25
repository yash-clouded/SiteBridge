"""SiteBridge backend configuration (env-overridable, see .env.example)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "SiteBridge"
    environment: str = "development"

    # PostgreSQL (+ pgvector from docker-compose; extension is enabled in Phase 5)
    database_url: str = "postgresql+psycopg://sitebridge:sitebridge@localhost:5432/sitebridge"

    # CORS for the Next.js dev server
    frontend_origin: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
