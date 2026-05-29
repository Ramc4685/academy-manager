"""Settings fallback tests for existing production deploy variables."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.v2.shared.config.settings import Settings


def _clear_production_env(monkeypatch) -> None:
    for name in (
        "APP_ENV",
        "V2_ENV",
        "MONGO_URL",
        "DB_NAME",
        "V2_MONGO_URL",
        "V2_MONGO_DB",
        "FIREBASE_PROJECT_ID",
        "V2_FIREBASE_PROJECT_ID",
        "STRIPE_API_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "V2_STRIPE_API_KEY",
        "V2_STRIPE_WEBHOOK_SECRET",
        "V2_STRIPE_USE_FAKE_GATEWAY",
        "JWT_SECRET",
        "CORS_ORIGINS",
        "V2_CORS_ORIGINS",
        "FRONTEND_URL",
        "V2_FRONTEND_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_settings_reuse_legacy_deploy_env_names(monkeypatch) -> None:
    monkeypatch.delenv("V2_ENV", raising=False)
    monkeypatch.delenv("V2_MONGO_URL", raising=False)
    monkeypatch.delenv("V2_MONGO_DB", raising=False)
    monkeypatch.delenv("V2_STRIPE_API_KEY", raising=False)
    monkeypatch.delenv("V2_STRIPE_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MONGO_URL", "mongodb+srv://legacy")
    monkeypatch.setenv("DB_NAME", "legacy_db")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "academy-courtmastr")
    monkeypatch.setenv("V2_STRIPE_USE_FAKE_GATEWAY", "false")
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_existing")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_existing")

    settings = Settings(_env_file=None)

    assert settings.env == "prod"
    assert settings.mongo_url == "mongodb+srv://legacy"
    assert settings.mongo_db == "legacy_db"
    assert settings.stripe_api_key == "sk_test_existing"
    assert settings.stripe_webhook_secret == "whsec_existing"


def test_v2_env_names_win_over_legacy_names(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MONGO_URL", "mongodb+srv://legacy")
    monkeypatch.setenv("DB_NAME", "legacy_db")
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_legacy")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_legacy")
    monkeypatch.setenv("V2_ENV", "staging")
    monkeypatch.setenv("V2_MONGO_URL", "mongodb+srv://v2")
    monkeypatch.setenv("V2_MONGO_DB", "v2_db")
    monkeypatch.setenv("V2_STRIPE_API_KEY", "sk_test_v2")
    monkeypatch.setenv("V2_STRIPE_WEBHOOK_SECRET", "whsec_v2")

    settings = Settings(_env_file=None)

    assert settings.env == "staging"
    assert settings.mongo_url == "mongodb+srv://v2"
    assert settings.mongo_db == "v2_db"
    assert settings.stripe_api_key == "sk_test_v2"
    assert settings.stripe_webhook_secret == "whsec_v2"


def test_saas_mode_defaults_to_false(monkeypatch) -> None:
    monkeypatch.delenv("V2_SAAS_MODE", raising=False)

    settings = Settings(_env_file=None)

    assert settings.saas_mode is False


def test_saas_mode_enabled_via_env(monkeypatch) -> None:
    monkeypatch.setenv("V2_SAAS_MODE", "true")

    settings = Settings(_env_file=None)

    assert settings.saas_mode is True


def test_saas_mode_false_non_saas_config(monkeypatch) -> None:
    monkeypatch.setenv("V2_SAAS_MODE", "false")

    settings = Settings(_env_file=None)

    assert settings.saas_mode is False
    assert settings.default_academy_id != ""


def test_allowed_internal_tenant_header_defaults_to_none(monkeypatch) -> None:
    monkeypatch.delenv("V2_ALLOWED_INTERNAL_TENANT_HEADER", raising=False)

    settings = Settings(_env_file=None)

    assert settings.allowed_internal_tenant_header is None


def test_allowed_internal_tenant_header_set_via_env(monkeypatch) -> None:
    monkeypatch.setenv("V2_ALLOWED_INTERNAL_TENANT_HEADER", "X-Internal-Academy-Id")

    settings = Settings(_env_file=None)

    assert settings.allowed_internal_tenant_header == "X-Internal-Academy-Id"


def test_prod_settings_require_explicit_mongo_and_firebase_project(monkeypatch) -> None:
    _clear_production_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")

    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None)

    message = str(exc.value)
    assert "mongo_url" in message
    assert "mongo_db" in message
    assert "firebase_project_id" in message
    assert "jwt" not in message.lower()


def test_prod_settings_allow_missing_jwt_secret(monkeypatch) -> None:
    _clear_production_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MONGO_URL", "mongodb+srv://prod")
    monkeypatch.setenv("DB_NAME", "academy_prod")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "academy-courtmastr")
    monkeypatch.setenv("V2_STRIPE_USE_FAKE_GATEWAY", "false")
    monkeypatch.setenv("STRIPE_API_KEY", "sk_live_existing")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_existing")

    settings = Settings(_env_file=None)

    assert settings.env == "prod"
    assert settings.firebase_project_id == "academy-courtmastr"


def test_prod_settings_require_stripe_secrets_when_real_gateway_enabled(monkeypatch) -> None:
    _clear_production_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MONGO_URL", "mongodb+srv://prod")
    monkeypatch.setenv("DB_NAME", "academy_prod")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "academy-courtmastr")
    monkeypatch.setenv("V2_STRIPE_USE_FAKE_GATEWAY", "false")

    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None)

    message = str(exc.value)
    assert "stripe_api_key" in message
    assert "stripe_webhook_secret" in message


def test_prod_settings_forbid_fake_stripe_gateway(monkeypatch) -> None:
    _clear_production_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MONGO_URL", "mongodb+srv://prod")
    monkeypatch.setenv("DB_NAME", "academy_prod")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "academy-courtmastr")
    monkeypatch.setenv("STRIPE_API_KEY", "sk_live_existing")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_existing")

    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None)

    assert "stripe_use_fake_gateway=false" in str(exc.value)


def test_cors_origins_reuse_existing_env_and_dedupe(monkeypatch) -> None:
    monkeypatch.delenv("V2_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("V2_FRONTEND_URL", raising=False)
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example, https://b.example")
    monkeypatch.setenv("FRONTEND_URL", "https://a.example")

    settings = Settings(_env_file=None)

    assert settings.cors_allowed_origins() == ["https://a.example", "https://b.example"]
