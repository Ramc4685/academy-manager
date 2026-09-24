"""Boot warning when OPS_ALERT_EMAIL is unset (roadmap D10).

The ops digest skips silently every cycle without a recipient; startup must
say so once, at WARNING, with the environment name.
"""

from __future__ import annotations

import inspect
import logging
from types import SimpleNamespace

import pytest

from backend.v2 import main as v2_main
from backend.v2.shared.observability import ops_alerts

EVENT = "ops_alert_email_missing"


@pytest.fixture(autouse=True)
def _reset_once_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ops_alerts, "_ops_alert_email_warned", False)


def _records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if getattr(r, "event", None) == EVENT]


@pytest.mark.parametrize("value", ["", None, "   "])
def test_missing_email_warns_exactly_once_per_process(
    caplog: pytest.LogCaptureFixture, value: str | None
) -> None:
    settings = SimpleNamespace(ops_alert_email=value, env="prod")
    with caplog.at_level(logging.WARNING, logger=ops_alerts.__name__):
        assert ops_alerts.warn_if_ops_alert_email_missing(settings) is True
        assert ops_alerts.warn_if_ops_alert_email_missing(settings) is False
    records = _records(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert records[0].env == "prod"  # type: ignore[attr-defined]
    assert "env=prod" in records[0].getMessage()


def test_configured_email_does_not_warn(caplog: pytest.LogCaptureFixture) -> None:
    settings = SimpleNamespace(ops_alert_email="ops@example.test", env="prod")
    with caplog.at_level(logging.WARNING, logger=ops_alerts.__name__):
        assert ops_alerts.warn_if_ops_alert_email_missing(settings) is False
    assert _records(caplog) == []


def test_lifespan_calls_warning_at_startup_not_in_digest_job() -> None:
    source = inspect.getsource(v2_main._lifespan)
    assert source.count("warn_if_ops_alert_email_missing(settings)") == 1
    # Called before the scheduler/job wiring, i.e. once per process at boot.
    assert source.index("warn_if_ops_alert_email_missing") < source.index("_send_ops_digest_body")
