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
    max_poll_timeout: int = 30
    max_poll_state_path: str = "/var/lib/dompuls-bot/state.json"
    max_default_house_id: str = "demo-house-a"
    max_miniapp_url: str = "http://localhost:3000"
    max_init_data_max_age_seconds: int = 3600
    dompuls_api_url: str = "http://api:8000"
    llm_mode: str = "deterministic"
    llm_api_key: str | None = None
    log_level: str = "INFO"

    @field_validator("max_mode")
    @classmethod
    def validate_max_mode(cls, value: str) -> str:
        if value not in {"simulated", "real"}:
            raise ValueError("MAX_MODE must be simulated or real")
        return value

    @field_validator("max_poll_timeout")
    @classmethod
    def validate_poll_timeout(cls, value: int) -> int:
        if not 1 <= value <= 90:
            raise ValueError("MAX_POLL_TIMEOUT must be between 1 and 90 seconds")
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
