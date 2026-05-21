"""Settings fallback tests for existing production deploy variables."""

from __future__ import annotations

from backend.v2.shared.config.settings import Settings


def test_settings_reuse_legacy_deploy_env_names(monkeypatch) -> None:
    monkeypatch.delenv("V2_ENV", raising=False)
    monkeypatch.delenv("V2_MONGO_URL", raising=False)
    monkeypatch.delenv("V2_MONGO_DB", raising=False)
    monkeypatch.delenv("V2_STRIPE_API_KEY", raising=False)
    monkeypatch.delenv("V2_STRIPE_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MONGO_URL", "mongodb+srv://legacy")
    monkeypatch.setenv("DB_NAME", "legacy_db")
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
