"""L11 wiring: settings that turn on the reliability features, and the boot /
healthz warning for production email that cannot ingest bounces or honour
unsubscribes (item 9)."""

from __future__ import annotations

from types import SimpleNamespace

from backend.v2.composition.digests import _build_email_sender
from backend.v2.contexts.communications.infrastructure.resend_send_port import (
    ResendEmailSendPort,
)
from backend.v2.shared.config.settings import Settings
from backend.v2.shared.observability.health import build_health_report


def _settings(**overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "env": "prod",
        "email_delivery_enabled": True,
        "resend_api_key": "re_test",
        "sender_email": "noreply@example.test",
        "frontend_url": "https://app.example.test",
        "marketing_sender_email": None,
        "email_send_max_retries": 0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_defaults_keep_todays_sender() -> None:
    port = _build_email_sender(_settings())
    assert isinstance(port, ResendEmailSendPort)
    assert port._marketing_from_address is None
    assert port._max_retries == 0


def test_marketing_sender_and_retries_reach_the_adapter() -> None:
    port = _build_email_sender(
        _settings(marketing_sender_email="news@mail.example.test", email_send_max_retries=3)
    )
    assert isinstance(port, ResendEmailSendPort)
    assert port._marketing_from_address == "news@mail.example.test"
    assert port._max_retries == 3


def test_settings_defaults_are_inert() -> None:
    fields = Settings.model_fields
    assert fields["marketing_sender_email"].default is None
    assert fields["email_send_max_retries"].default == 0
    assert fields["email_list_unsubscribe_enabled"].default is False
    assert "dunning_signed_pay_link_enabled" not in fields


def _construct(**values: object) -> Settings:
    base: dict[str, object] = {
        "env": "prod",
        "email_delivery_enabled": True,
        "resend_api_key": "re_test",
        "resend_webhook_secret": None,
        "unsubscribe_token_secret": None,
    }
    base.update(values)
    return Settings.model_construct(**base)


def test_production_email_without_bounce_or_unsubscribe_secrets_warns() -> None:
    warnings = _construct().email_config_warnings()
    assert len(warnings) == 2
    assert any("RESEND_WEBHOOK_SECRET" in w for w in warnings)
    assert any("UNSUBSCRIBE_TOKEN_SECRET" in w for w in warnings)


def test_no_warning_when_configured_or_not_sending() -> None:
    assert (
        _construct(
            resend_webhook_secret="whsec_x", unsubscribe_token_secret="s"
        ).email_config_warnings()
        == []
    )
    assert _construct(email_delivery_enabled=False).email_config_warnings() == []
    assert _construct(env="dev").email_config_warnings() == []


async def test_healthz_reports_config_warnings_without_failing() -> None:
    report, healthy = await build_health_report(config_warnings=["bounce ingestion is off"])
    assert healthy is True
    assert report["warnings"] == ["bounce ingestion is off"]

    report, _ = await build_health_report()
    assert "warnings" not in report
