"""Application configuration for v2.

Sources values from env via pydantic-settings. Single source of truth — no
direct os.environ reads outside this module.
"""

from __future__ import annotations

from functools import lru_cache
import os
from typing import Literal

from pydantic import Field, model_validator
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

    @model_validator(mode="after")
    def apply_legacy_deploy_fallbacks(self) -> "Settings":
        """Reuse existing production deploy env names when V2_* is absent.

        The legacy Fly app already owns MONGO_URL, DB_NAME, STRIPE_API_KEY,
        and STRIPE_WEBHOOK_SECRET. V2-specific names still win when present,
        but these fallbacks let v2 mount in the existing deployment without
        duplicating hidden secrets.
        """

        if "V2_ENV" not in os.environ:
            app_env = os.environ.get("APP_ENV", "").lower()
            if app_env in {"production", "prod"}:
                self.env = "prod"
            elif app_env == "staging":
                self.env = "staging"
            elif app_env == "test":
                self.env = "test"

        if "V2_MONGO_URL" not in os.environ:
            self.mongo_url = os.environ.get("MONGO_URL", self.mongo_url)
        if "V2_MONGO_DB" not in os.environ:
            self.mongo_db = os.environ.get("DB_NAME", self.mongo_db)
        if "V2_STRIPE_API_KEY" not in os.environ:
            self.stripe_api_key = os.environ.get("STRIPE_API_KEY", self.stripe_api_key)
        if "V2_STRIPE_WEBHOOK_SECRET" not in os.environ:
            self.stripe_webhook_secret = os.environ.get(
                "STRIPE_WEBHOOK_SECRET", self.stripe_webhook_secret
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
