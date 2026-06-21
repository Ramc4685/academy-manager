"""Application configuration for v2.

Sources values from env via pydantic-settings. Single source of truth — no
direct os.environ reads outside this module.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
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
            "value today; multi-tenancy is a config flip later. "
            "In SaaS mode (saas_mode=True) this value is ignored for tenant resolution."
        ),
    )

    saas_mode: bool = Field(
        default=False,
        description=(
            "SaaS multi-tenant mode per ADR-0007. When True, legacy /api/* routes are "
            "forbidden and default_academy_id is not a valid tenant source."
        ),
    )
    tenancy_mode: Literal["multi_academy", "single_academy"] = Field(
        default="multi_academy",
        description=(
            "Launch tenancy mode. In single_academy mode every resolved request tenant "
            "must match primary_academy_id."
        ),
    )
    primary_academy_id: str | None = Field(default=None)
    enable_platform_routes: bool = Field(default=True)
    enable_owner_role: bool = Field(default=False)
    enable_student_login: bool = Field(default=False)

    allowed_internal_tenant_header: str | None = Field(
        default=None,
        description=(
            "Header name accepted as an internal tenant source. Only honoured when "
            "saas_mode=True and the value is non-None. Used for internal jobs and "
            "platform admin tooling only."
        ),
    )

    run_migrations_on_boot: bool = Field(default=False)

    otel_exporter_otlp_endpoint: str | None = Field(default=None)
    otel_sampling_ratio: float = Field(default=0.1, ge=0.0, le=1.0)

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")
    log_format: Literal["json", "console"] = Field(default="json")

    stripe_api_key: str | None = Field(default=None)
    stripe_webhook_secret: str | None = Field(default=None)
    stripe_connect_client_id: str | None = Field(default=None)
    stripe_connect_callback_uri: str | None = Field(default=None)
    stripe_connect_state_secret: str | None = Field(default=None)
    firebase_project_id: str | None = Field(default=None)
    cors_origins: str = Field(default="")
    frontend_url: str | None = Field(default=None)
    scheduler_tz: str = Field(default="UTC")
    resend_api_key: str | None = Field(default=None)
    sender_email: str | None = Field(default=None)
    email_delivery_enabled: bool = Field(
        default=False,
        description="When True and resend_api_key is set, emails are sent via Resend. Stub adapter used otherwise.",
    )
    coach_digest_enabled: bool = Field(
        default=False,
        description="When True, the daily coach teaching-plan digest cron job is registered.",
    )
    coach_digest_hour: int = Field(
        default=6,
        ge=0,
        le=23,
        description="Hour (scheduler TZ) at which the daily coach digest job runs.",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _normalize_cors_origins(cls, value: object) -> str:
        if isinstance(value, list | tuple):
            return ",".join(str(item) for item in value)
        return str(value or "")

    @model_validator(mode="after")
    def apply_legacy_deploy_fallbacks(self) -> Settings:
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
        if "V2_TENANCY_MODE" not in os.environ and os.environ.get("APP_TENANCY_MODE"):
            self.tenancy_mode = os.environ["APP_TENANCY_MODE"].strip().lower()  # type: ignore[assignment]
        if "V2_PRIMARY_ACADEMY_ID" not in os.environ:
            self.primary_academy_id = os.environ.get("PRIMARY_ACADEMY_ID", self.primary_academy_id)
        if "V2_ENABLE_PLATFORM_ROUTES" not in os.environ:
            self.enable_platform_routes = _env_bool(
                "ENABLE_PLATFORM_ROUTES",
                self.enable_platform_routes,
            )
        if "V2_ENABLE_OWNER_ROLE" not in os.environ:
            self.enable_owner_role = _env_bool("ENABLE_OWNER_ROLE", self.enable_owner_role)
        if "V2_ENABLE_STUDENT_LOGIN" not in os.environ:
            self.enable_student_login = _env_bool(
                "ENABLE_STUDENT_LOGIN",
                self.enable_student_login,
            )
        if "V2_STRIPE_CONNECT_CLIENT_ID" not in os.environ:
            self.stripe_connect_client_id = os.environ.get(
                "STRIPE_CONNECT_CLIENT_ID", self.stripe_connect_client_id
            )
        if "V2_STRIPE_CONNECT_CALLBACK_URI" not in os.environ:
            self.stripe_connect_callback_uri = os.environ.get(
                "STRIPE_CONNECT_CALLBACK_URI", self.stripe_connect_callback_uri
            )
        if "V2_FIREBASE_PROJECT_ID" not in os.environ:
            self.firebase_project_id = os.environ.get(
                "FIREBASE_PROJECT_ID", self.firebase_project_id
            )
        if "V2_CORS_ORIGINS" not in os.environ:
            self.cors_origins = os.environ.get("CORS_ORIGINS", self.cors_origins)
        if "V2_FRONTEND_URL" not in os.environ:
            self.frontend_url = os.environ.get("FRONTEND_URL", self.frontend_url)
        if "V2_SCHEDULER_TZ" not in os.environ:
            self.scheduler_tz = os.environ.get("SCHEDULER_TZ", self.scheduler_tz)
        if "V2_SENDER_EMAIL" not in os.environ:
            self.sender_email = os.environ.get("SENDER_EMAIL", self.sender_email)
        if "V2_EMAIL_DELIVERY_ENABLED" not in os.environ:
            self.email_delivery_enabled = _env_bool(
                "EMAIL_DELIVERY_ENABLED",
                self.email_delivery_enabled,
            )
        self._validate_launch_settings()
        self._validate_production_settings()
        return self

    def cors_allowed_origins(self) -> list[str]:
        values = [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
        if self.frontend_url:
            values.append(self.frontend_url.strip())
        unique: list[str] = []
        seen: set[str] = set()
        for origin in values:
            if origin not in seen:
                unique.append(origin)
                seen.add(origin)
        return unique

    def _validate_production_settings(self) -> None:
        if self.env != "prod":
            return

        missing: list[str] = []
        if not _explicit_env_value("V2_MONGO_URL", "MONGO_URL"):
            missing.append("mongo_url")
        if not _explicit_env_value("V2_MONGO_DB", "DB_NAME"):
            missing.append("mongo_db")
        if not _explicit_env_value("V2_FIREBASE_PROJECT_ID", "FIREBASE_PROJECT_ID"):
            missing.append("firebase_project_id")
        if not _explicit_env_value("V2_STRIPE_API_KEY", "STRIPE_API_KEY"):
            missing.append("stripe_api_key")
        if not _explicit_env_value("V2_STRIPE_WEBHOOK_SECRET", "STRIPE_WEBHOOK_SECRET"):
            missing.append("stripe_webhook_secret")
        if "*" in self.cors_allowed_origins():
            missing.append("cors_origins_without_wildcard")

        if missing:
            missing_text = ", ".join(missing)
            raise ValueError(f"Missing required production v2 settings: {missing_text}")

    def _validate_launch_settings(self) -> None:
        if self.tenancy_mode not in {"multi_academy", "single_academy"}:
            raise ValueError(f"Unsupported tenancy_mode: {self.tenancy_mode}")
        if self.tenancy_mode == "single_academy" and not (
            self.primary_academy_id and self.primary_academy_id.strip()
        ):
            raise ValueError("primary_academy_id is required when tenancy_mode=single_academy")
        if (
            self.env == "prod"
            and self.tenancy_mode == "single_academy"
            and self.enable_platform_routes
        ):
            raise ValueError(
                "enable_platform_routes must be false for production single_academy launch"
            )


def _explicit_env_value(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value is not None and value.strip():
            return value
    return None


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
