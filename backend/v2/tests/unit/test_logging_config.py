"""configure_logging(): uvicorn access-log interaction + third-party log noise.

Production runs ``uvicorn --no-access-log`` and calls ``configure_logging()``
from the app lifespan, i.e. *after* uvicorn has configured logging. These tests
pin the two behaviours that keep Sentry Logs volume down: a disabled access
logger stays disabled, and chatty third-party loggers are held at WARNING
unless the developer asked for DEBUG.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest

from backend.v2.shared.config.settings import get_settings
from backend.v2.shared.observability.logging import (
    QUIET_THIRD_PARTY_LOGGERS,
    configure_logging,
)

_TOUCHED_LOGGERS = (
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    *(name for name, _ in QUIET_THIRD_PARTY_LOGGERS),
)


@pytest.fixture
def restore_logging(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Snapshot root + every logger configure_logging() touches; restore after."""
    monkeypatch.delenv("V2_LOG_FORMAT", raising=False)
    monkeypatch.delenv("V2_LOG_LEVEL", raising=False)
    root = logging.getLogger()
    saved_root = (list(root.handlers), root.level)
    saved = {
        name: (list(lg.handlers), lg.propagate, lg.level)
        for name, lg in ((n, logging.getLogger(n)) for n in _TOUCHED_LOGGERS)
    }
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()
        root.handlers[:], level = saved_root
        root.setLevel(level)
        for name, (handlers, propagate, lvl) in saved.items():
            lg = logging.getLogger(name)
            lg.handlers[:] = handlers
            lg.propagate = propagate
            lg.setLevel(lvl)


def _set_root_level(monkeypatch: pytest.MonkeyPatch, level: str) -> None:
    monkeypatch.setenv("V2_LOG_LEVEL", level)
    get_settings.cache_clear()


def test_disabled_uvicorn_access_logger_stays_disabled(restore_logging, monkeypatch) -> None:
    # Exactly what ``uvicorn --no-access-log`` leaves behind.
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False
    error = logging.getLogger("uvicorn.error")
    error.addHandler(logging.NullHandler())
    error.propagate = False
    _set_root_level(monkeypatch, "INFO")

    configure_logging()

    assert access.handlers == [] and access.propagate is False
    # The other uvicorn loggers are still re-routed through the JSON root handler.
    assert error.handlers == [] and error.propagate is True


def test_enabled_uvicorn_access_logger_is_routed_through_root(restore_logging, monkeypatch) -> None:
    # uvicorn's default dictConfig: a plain-text handler and no propagation.
    access = logging.getLogger("uvicorn.access")
    access.handlers[:] = [logging.NullHandler()]
    access.propagate = False
    _set_root_level(monkeypatch, "INFO")

    configure_logging()

    assert access.handlers == [] and access.propagate is True


def test_third_party_loggers_are_quieted_at_info_root(restore_logging, monkeypatch) -> None:
    for name, _ in QUIET_THIRD_PARTY_LOGGERS:
        logging.getLogger(name).setLevel(logging.NOTSET)
    _set_root_level(monkeypatch, "INFO")

    configure_logging()

    assert logging.getLogger().level == logging.INFO
    for name, level in QUIET_THIRD_PARTY_LOGGERS:
        assert logging.getLogger(name).level == level, name
        assert not logging.getLogger(name).isEnabledFor(logging.INFO), name
    # Application loggers are untouched.
    assert logging.getLogger("backend.v2.app").isEnabledFor(logging.INFO)


def test_third_party_loggers_are_left_alone_at_debug_root(restore_logging, monkeypatch) -> None:
    _set_root_level(monkeypatch, "DEBUG")

    configure_logging()

    assert logging.getLogger().level == logging.DEBUG
    for name, _ in QUIET_THIRD_PARTY_LOGGERS:
        assert logging.getLogger(name).level == logging.NOTSET, name
        assert logging.getLogger(name).isEnabledFor(logging.DEBUG), name


def test_debug_root_undoes_an_earlier_quieting(restore_logging, monkeypatch) -> None:
    """Reconfiguring at DEBUG (e.g. reload) must not keep the WARNING clamp."""
    _set_root_level(monkeypatch, "INFO")
    configure_logging()
    assert logging.getLogger("stripe").level == logging.WARNING

    _set_root_level(monkeypatch, "DEBUG")
    configure_logging()
    assert logging.getLogger("stripe").level == logging.NOTSET
