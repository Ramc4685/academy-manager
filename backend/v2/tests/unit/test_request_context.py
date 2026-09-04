"""Audit C2: request correlation middleware + context log filter + Sentry gate."""

from __future__ import annotations

import io
import json
import logging
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.shared.config import Settings
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.observability.errors import (
    _keep_log,
    _tag_event,
    configure_error_tracking,
    resolve_release,
)
from backend.v2.shared.observability.logging import _JsonFormatter, configure_logging
from backend.v2.shared.observability.request_context import (
    REQUEST_ID_HEADER,
    ContextLogFilter,
    RequestContextMiddleware,
    RequestLogMiddleware,
    _request_id,
    current_request_id,
)
from backend.v2.shared.tenancy.context import tenant_scope


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/probe")
    async def _probe() -> dict[str, str | None]:
        return {"request_id": current_request_id()}

    return app


def test_middleware_generates_request_id_when_absent() -> None:
    with TestClient(_app()) as client:
        response = client.get("/probe")

    generated = response.headers[REQUEST_ID_HEADER]
    assert generated
    assert response.json()["request_id"] == generated


def test_middleware_echoes_inbound_x_request_id() -> None:
    with TestClient(_app()) as client:
        response = client.get("/probe", headers={"X-Request-ID": "rid-123"})

    assert response.headers[REQUEST_ID_HEADER] == "rid-123"
    assert response.json()["request_id"] == "rid-123"


def test_middleware_accepts_fly_request_id_as_fallback() -> None:
    with TestClient(_app()) as client:
        response = client.get("/probe", headers={"Fly-Request-Id": "fly-456"})

    assert response.headers[REQUEST_ID_HEADER] == "fly-456"


def test_middleware_rejects_unsafe_inbound_request_id() -> None:
    with TestClient(_app()) as client:
        response = client.get("/probe", headers={"X-Request-ID": "x" * 300})

    echoed = response.headers[REQUEST_ID_HEADER]
    assert echoed != "x" * 300
    assert len(echoed) == 32  # uuid4().hex fallback


def test_context_is_cleared_after_the_request() -> None:
    with TestClient(_app()) as client:
        client.get("/probe", headers={"X-Request-ID": "rid-123"})

    assert current_request_id() is None


def test_context_log_filter_stamps_json_output() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(ContextLogFilter())
    handler.setFormatter(_JsonFormatter())
    logger = logging.getLogger("test.request_context")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False

    token = _request_id.set("rid-789")
    try:
        with tenant_scope("academy-1"):
            logger.info("hello")
    finally:
        _request_id.reset(token)
        logger.removeHandler(handler)

    payload = json.loads(stream.getvalue())
    assert payload["request_id"] == "rid-789"
    assert payload["academy_id"] == "academy-1"
    assert payload["message"] == "hello"


def _format(record: logging.LogRecord) -> dict[str, Any]:
    return json.loads(_JsonFormatter().format(record))


def _record(msg: str = "msg", **extra: Any) -> logging.LogRecord:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, msg, None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_includes_extra_fields() -> None:
    payload = _format(_record(job_id="job-1", checks={"mongo": "ok"}))

    assert payload["job_id"] == "job-1"
    assert payload["checks"] == {"mongo": "ok"}
    # Standard LogRecord plumbing never leaks into the payload.
    assert "args" not in payload
    assert "levelno" not in payload
    assert "pathname" not in payload


def test_json_formatter_never_clobbers_reserved_keys() -> None:
    record = _record(
        "real message", level="spoofed", logger="spoofed", timestamp="spoofed", exception="spoofed"
    )

    payload = _format(record)

    assert payload["message"] == "real message"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "t"
    assert payload["timestamp"] != "spoofed"
    assert "exception" not in payload


def test_json_formatter_stringifies_non_serialisable_values() -> None:
    when = datetime(2026, 9, 3, tzinfo=UTC)
    payload = _format(_record(when=when, exc=ValueError("boom")))

    assert payload["when"] == str(when)
    assert payload["exc"] == "boom"


def test_configure_logging_routes_uvicorn_loggers_through_root(monkeypatch) -> None:
    monkeypatch.delenv("V2_LOG_FORMAT", raising=False)
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    access = logging.getLogger("uvicorn.access")
    error = logging.getLogger("uvicorn.error")
    original = {
        "root": list(logging.getLogger().handlers),
        "root_level": logging.getLogger().level,
        "access": (list(access.handlers), access.propagate),
        "error": (list(error.handlers), error.propagate),
    }
    # Mimic uvicorn's own plain-text setup.
    access.addHandler(logging.NullHandler())
    access.propagate = False
    error.addHandler(logging.NullHandler())
    error.propagate = False
    try:
        configure_logging()

        assert access.handlers == [] and access.propagate is True
        assert error.handlers == [] and error.propagate is True
        root_handlers = logging.getLogger().handlers
        assert len(root_handlers) == 1
        assert isinstance(root_handlers[0].formatter, _JsonFormatter)
        assert any(isinstance(f, ContextLogFilter) for f in root_handlers[0].filters)
    finally:
        root = logging.getLogger()
        root.handlers[:] = original["root"]
        root.setLevel(original["root_level"])
        access.handlers[:], access.propagate = original["access"]
        error.handlers[:], error.propagate = original["error"]


def _logged_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(RequestLogMiddleware)
    app.add_middleware(RequestContextMiddleware)

    @app.get("/items/{item_id}")
    async def _item(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    @app.get("/api/v2/healthz")
    async def _healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/boom")
    async def _boom() -> None:
        raise RuntimeError("kaboom")

    return app


def _request_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "backend.v2.http.request"]


def test_request_log_line_carries_method_route_status_duration_and_request_id(caplog) -> None:
    with caplog.at_level(logging.INFO), TestClient(_logged_app()) as client:
        response = client.get("/items/42", headers={"X-Request-ID": "rid-log"})

    assert response.status_code == 200
    (record,) = _request_records(caplog)
    assert record.levelno == logging.INFO
    assert record.method == "GET"
    assert record.path == "/items/42"
    assert record.route == "/items/{item_id}"
    assert record.status_code == 200
    assert isinstance(record.duration_ms, float) and record.duration_ms >= 0
    assert record.getMessage() == "GET /items/42 -> 200"
    # The context filter (root handler) is what stamps request_id in prod;
    # the middleware runs inside RequestContextMiddleware so it is available.
    assert ContextLogFilter().filter(record) is True
    payload = json.loads(_JsonFormatter().format(record))
    assert payload["method"] == "GET"
    assert payload["status_code"] == 200
    assert "duration_ms" in payload


def test_request_log_stamps_request_id_when_formatted_in_context(caplog) -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(ContextLogFilter())
    handler.setFormatter(_JsonFormatter())
    logger = logging.getLogger("backend.v2.http.request")
    logger.addHandler(handler)
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        with TestClient(_logged_app()) as client:
            client.get("/items/1", headers={"X-Request-ID": "rid-in-line"})
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)

    payload = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert payload["request_id"] == "rid-in-line"
    assert payload["route"] == "/items/{item_id}"


def test_request_log_demotes_healthz_to_debug(caplog) -> None:
    with caplog.at_level(logging.DEBUG), TestClient(_logged_app()) as client:
        client.get("/api/v2/healthz")

    (record,) = _request_records(caplog)
    assert record.levelno == logging.DEBUG
    assert record.path == "/api/v2/healthz"


def test_unhandled_error_is_logged_once_with_context_and_still_returns_500(caplog) -> None:
    with (
        caplog.at_level(logging.INFO),
        TestClient(_logged_app(), raise_server_exceptions=False) as client,
    ):
        response = client.get("/boom", headers={"X-Request-ID": "rid-500"})

    assert response.status_code == 500
    errors = [r for r in caplog.records if r.name == "backend.v2.http"]
    (error,) = errors
    assert error.levelno == logging.ERROR
    assert error.method == "GET"
    assert error.path == "/boom"
    assert error.exception_type == "RuntimeError"
    assert error.exc_info is not None and error.exc_info[0] is RuntimeError
    assert "kaboom" in _JsonFormatter().format(error)
    # The request line still fires, as a 500, when the exception escapes.
    (request_line,) = _request_records(caplog)
    assert request_line.status_code == 500


def test_unhandled_error_handler_reraises_for_the_server(caplog) -> None:
    with (
        caplog.at_level(logging.ERROR),
        pytest.raises(RuntimeError, match="kaboom"),
        TestClient(_logged_app()) as client,
    ):
        client.get("/boom")

    assert any(r.name == "backend.v2.http" for r in caplog.records)


def test_domain_error_handler_is_unchanged_by_catch_all(caplog) -> None:
    from backend.v2.shared.http import DomainError

    class Rejected(DomainError):
        code = "Rejected"
        status_code = 409

    app = _logged_app()

    @app.get("/reject")
    async def _reject() -> None:
        raise Rejected("nope")

    with caplog.at_level(logging.INFO), TestClient(app) as client:
        response = client.get("/reject")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "Rejected"
    assert not [r for r in caplog.records if r.name == "backend.v2.http"]


def test_resolve_release_prefers_explicit_env_then_fly_image_ref(monkeypatch) -> None:
    for name in ("V2_SENTRY_RELEASE", "SENTRY_RELEASE", "FLY_IMAGE_REF"):
        monkeypatch.delenv(name, raising=False)
    assert resolve_release() is None

    monkeypatch.setenv("FLY_IMAGE_REF", "registry.fly.io/app:deployment-abc")
    assert resolve_release() == "registry.fly.io/app:deployment-abc"

    monkeypatch.setenv("SENTRY_RELEASE", "v1.2.3")
    assert resolve_release() == "v1.2.3"

    monkeypatch.setenv("V2_SENTRY_RELEASE", "v9")
    assert resolve_release() == "v9"


def test_sentry_init_receives_release_when_set(monkeypatch) -> None:
    import sentry_sdk

    monkeypatch.delenv("V2_SENTRY_RELEASE", raising=False)
    monkeypatch.delenv("SENTRY_RELEASE", raising=False)
    monkeypatch.setenv("FLY_IMAGE_REF", "registry.fly.io/app:deployment-xyz")
    captured: dict[str, Any] = {}
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: captured.update(kwargs))

    # Pin env explicitly: CI exports V2_ENV=test, local shells default to dev.
    settings = Settings(sentry_dsn="https://key@sentry.example/1", env="staging")
    configure_error_tracking(settings)

    assert captured["release"] == "registry.fly.io/app:deployment-xyz"
    assert captured["environment"] == "staging"


def test_sentry_init_omits_release_when_nothing_is_set(monkeypatch) -> None:
    import sentry_sdk

    for name in ("V2_SENTRY_RELEASE", "SENTRY_RELEASE", "FLY_IMAGE_REF"):
        monkeypatch.delenv(name, raising=False)
    captured: dict[str, Any] = {}
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: captured.update(kwargs))

    configure_error_tracking(Settings(sentry_dsn="https://key@sentry.example/1"))

    assert captured["release"] is None


def test_context_log_filter_is_a_noop_outside_request_and_tenant_scope() -> None:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "msg", None, None)
    assert ContextLogFilter().filter(record) is True
    assert getattr(record, "request_id", None) is None
    assert getattr(record, "academy_id", None) is None


def test_sentry_init_skipped_without_dsn(caplog, monkeypatch) -> None:
    # The legacy-fallback validator would resurrect a SENTRY_DSN exported in
    # the runner's environment and override the constructor argument.
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.delenv("V2_SENTRY_DSN", raising=False)
    settings = Settings(sentry_dsn=None)
    with caplog.at_level(logging.INFO):
        configure_error_tracking(settings)
    assert "error tracking disabled" in caplog.text

    import sentry_sdk

    assert not sentry_sdk.get_client().is_active()


def test_tag_event_reads_contextvars_at_event_time() -> None:
    token = _request_id.set("rid-tag")
    try:
        with tenant_scope("academy-2"):
            event = _tag_event({}, {})
    finally:
        _request_id.reset(token)

    assert event["tags"] == {"request_id": "rid-tag", "academy_id": "academy-2"}


def test_tag_event_without_context_leaves_tags_empty() -> None:
    event = _tag_event({}, {})
    assert event["tags"] == {}


def test_sentry_init_enables_logs_with_volume_guard(monkeypatch) -> None:
    import sentry_sdk

    captured: dict[str, Any] = {}
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: captured.update(kwargs))

    configure_error_tracking(Settings(sentry_dsn="https://key@sentry.example/1", env="staging"))

    assert captured["enable_logs"] is True
    assert captured["before_send_log"] is _keep_log
    logging_integrations = [
        i for i in captured["integrations"] if type(i).__name__ == "LoggingIntegration"
    ]
    assert len(logging_integrations) == 1
    assert logging_integrations[0]._sentry_logs_handler is not None
    assert logging_integrations[0]._handler is not None  # ERROR events unchanged


def test_sentry_logs_can_be_switched_off(monkeypatch) -> None:
    import sentry_sdk

    captured: dict[str, Any] = {}
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: captured.update(kwargs))

    configure_error_tracking(
        Settings(
            sentry_dsn="https://key@sentry.example/1", env="staging", sentry_logs_enabled=False
        )
    )

    assert captured["enable_logs"] is False
    (integration,) = [
        i for i in captured["integrations"] if type(i).__name__ == "LoggingIntegration"
    ]
    assert integration._sentry_logs_handler is None


def test_sentry_logs_env_fallback(monkeypatch) -> None:
    monkeypatch.delenv("V2_SENTRY_LOGS_ENABLED", raising=False)
    monkeypatch.setenv("SENTRY_LOGS_ENABLED", "false")
    assert Settings().sentry_logs_enabled is False
    monkeypatch.setenv("SENTRY_LOGS_ENABLED", "true")
    assert Settings().sentry_logs_enabled is True


def _log(body: str, logger: str = "backend.v2.app", severity_number: int = 9) -> dict[str, Any]:
    return {
        "severity_text": "info",
        "severity_number": severity_number,
        "body": body,
        "attributes": {"logger.name": logger},
        "time_unix_nano": 0,
        "trace_id": None,
    }


def test_keep_log_drops_noise_and_debug_but_keeps_app_lines() -> None:
    assert _keep_log(_log("boot ok"), {}) is not None
    assert (
        _keep_log(_log("GET /api/v2/healthz -> 200", logger="backend.v2.http.request"), {}) is None
    )
    assert _keep_log(_log("anything", logger="uvicorn.access"), {}) is None
    assert _keep_log(_log("verbose", severity_number=5), {}) is None
    kept = _keep_log(_log("GET /api/v2/me -> 200", logger="backend.v2.http.request"), {})
    assert kept is not None and kept["body"] == "GET /api/v2/me -> 200"
