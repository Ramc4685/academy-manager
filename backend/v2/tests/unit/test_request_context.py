"""Audit C2: request correlation middleware + context log filter + Sentry gate."""

from __future__ import annotations

import io
import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.shared.config import Settings
from backend.v2.shared.observability.errors import _tag_event, configure_error_tracking
from backend.v2.shared.observability.logging import _JsonFormatter
from backend.v2.shared.observability.request_context import (
    REQUEST_ID_HEADER,
    ContextLogFilter,
    RequestContextMiddleware,
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
