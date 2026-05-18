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
