"""Application configuration for v2.

Sources values from env via pydantic-settings. Single source of truth — no
direct os.environ reads outside this module.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="V2_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["dev", "staging", "prod", "test"] = Field(default="dev")

    mongo_url: str = Field(
        default="mongodb://localhost:27017",
        description="Mongo connection URI. Reused with the legacy app's cluster.",
    )
    mongo_db: str = Field(default="academy_manager")

    default_academy_id: str = Field(
        default="default-academy",
        description=(
            "Single-tenant academy ID per ADR-0006. Auth claims will carry this "
            "value today; multi-tenancy is a config flip later."
        ),
    )

    run_migrations_on_boot: bool = Field(default=False)

    otel_exporter_otlp_endpoint: str | None = Field(default=None)
    otel_sampling_ratio: float = Field(default=0.1, ge=0.0, le=1.0)

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")
    log_format: Literal["json", "console"] = Field(default="json")

    stripe_api_key: str | None = Field(default=None)
    stripe_webhook_secret: str | None = Field(default=None)
    stripe_use_fake_gateway: bool = Field(default=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
