from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./dompuls.sqlite3"
    cors_origins: str = "http://localhost:3000"
    max_mode: str = "simulated"
    max_bot_token: str | None = None
    max_webhook_secret: str | None = None
    max_api_base: str = "https://platform-api2.max.ru"
    max_ca_bundle: str | None = None
    llm_mode: str = "deterministic"
    llm_api_key: str | None = None
    log_level: str = "INFO"

    @field_validator("max_mode")
    @classmethod
    def validate_max_mode(cls, value: str) -> str:
        if value not in {"simulated", "real"}:
            raise ValueError("MAX_MODE must be simulated or real")
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
