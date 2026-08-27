"""Unit tests for the ops alerting slice (issue #428).

Covers the APScheduler error/missed listener callback and the ops-digest
content assembly. Both use fakes — no Mongo, no Sentry, no Resend.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.shared.observability import ops_alerts
from backend.v2.shared.observability.ops_digest import (
    INVOICE_GENERATION_JOB,
    JOB_RUNS_COLLECTION,
    OpsDigestSnapshot,
    collect_ops_digest,
    record_job_run,
    render_ops_digest,
)


class _FakeJobEvent:
    def __init__(
        self,
        *,
        job_id: str,
        code: int,
        exception: BaseException | None = None,
        scheduled_run_time: datetime | None = None,
    ) -> None:
        self.job_id = job_id
        self.code = code
        self.exception = exception
        self.scheduled_run_time = scheduled_run_time


class _SentrySpy:
    def __init__(self) -> None:
        self.exceptions: list[BaseException | None] = []
        self.messages: list[tuple[str, str]] = []

    def capture_exception(self, exc: BaseException | None = None) -> None:
        self.exceptions.append(exc)

    def capture_message(self, message: str, *, level: str = "error") -> None:
        self.messages.append((message, level))


@pytest.fixture
def sentry(monkeypatch: pytest.MonkeyPatch) -> _SentrySpy:
    spy = _SentrySpy()
    monkeypatch.setattr(ops_alerts, "_active_sentry", lambda: spy)
    return spy


@pytest.fixture
def no_sentry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ops_alerts, "_active_sentry", lambda: None)


# --- listener ---------------------------------------------------------------


def test_job_error_logs_and_reports_to_sentry(
    sentry: _SentrySpy, caplog: pytest.LogCaptureFixture
) -> None:
    boom = RuntimeError("boom")
    event = _FakeJobEvent(
        job_id="process_dunning_retries",
        code=2**7,
        exception=boom,
        scheduled_run_time=datetime(2026, 8, 27, 3, 0, tzinfo=UTC),
    )

    with caplog.at_level(logging.ERROR):
        ops_alerts.handle_scheduler_job_event(event)

    assert sentry.exceptions == [boom]
    record = next(r for r in caplog.records if "scheduler_job_error" in r.getMessage())
    assert record.job_id == "process_dunning_retries"
    assert record.scheduled_run_time == "2026-08-27T03:00:00+00:00"
    assert record.exc_info is not None


def test_job_missed_has_no_exception_so_reports_a_message(
    sentry: _SentrySpy, caplog: pytest.LogCaptureFixture
) -> None:
    event = _FakeJobEvent(job_id="generate_monthly_invoices", code=2**8)

    with caplog.at_level(logging.ERROR):
        ops_alerts.handle_scheduler_job_event(event)

    assert sentry.exceptions == []
    assert sentry.messages == [("Scheduler job missed: generate_monthly_invoices", "error")]
    assert any("scheduler_job_missed" in r.getMessage() for r in caplog.records)


def test_listener_still_logs_without_sentry(
    no_sentry: None, caplog: pytest.LogCaptureFixture
) -> None:
    event = _FakeJobEvent(job_id="send_ops_digest", code=2**7, exception=ValueError("nope"))

    with caplog.at_level(logging.ERROR):
        ops_alerts.handle_scheduler_job_event(event)

    assert any("scheduler_job_error" in r.getMessage() for r in caplog.records)


def test_listener_never_raises(sentry: _SentrySpy) -> None:
    class _Hostile:
        @property
        def job_id(self) -> str:
            raise RuntimeError("attribute access exploded")

    # APScheduler dispatches listeners inline; a raise here would take out the
    # notification for every other listener.
    ops_alerts.handle_scheduler_job_event(_Hostile())


def test_capture_exception_reports_whether_sentry_took_it(
    sentry: _SentrySpy, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert ops_alerts.capture_exception(RuntimeError("x")) is True
    monkeypatch.setattr(ops_alerts, "_active_sentry", lambda: None)
    assert ops_alerts.capture_exception(RuntimeError("x")) is False


# --- digest -----------------------------------------------------------------


class _FakeCollection:
    def __init__(self, docs: list[dict[str, Any]], *, fail: bool = False) -> None:
        self.docs = docs
        self.fail = fail
        self.updates: list[tuple[dict[str, Any], dict[str, Any]]] = []

    async def count_documents(self, query: dict[str, Any]) -> int:
        if self.fail:
            raise RuntimeError("collection unreadable")
        return sum(1 for doc in self.docs if _matches(doc, query))

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        return next((doc for doc in self.docs if _matches(doc, query)), None)

    async def update_one(
        self, query: dict[str, Any], update: dict[str, Any], upsert: bool = False
    ) -> None:
        self.updates.append((query, update))


def _matches(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        actual = doc.get(key)
        if isinstance(expected, dict) and "$gte" in expected:
            if actual is None or actual < expected["$gte"]:
                return False
        elif actual != expected:
            return False
    return True


class _FakeDb:
    def __init__(self, collections: dict[str, _FakeCollection]) -> None:
        self._collections = collections

    def __getitem__(self, name: str) -> _FakeCollection:
        return self._collections.setdefault(name, _FakeCollection([]))


NOW = datetime(2026, 8, 27, 7, 0, tzinfo=UTC)
RECENT = NOW - timedelta(hours=2)
OLD = NOW - timedelta(days=5)


def _db(**overrides: _FakeCollection) -> _FakeDb:
    collections: dict[str, _FakeCollection] = {
        "stripe_webhook_events": _FakeCollection(
            [
                {"status": "quarantined"},
                {"status": "quarantined"},
                {"status": "failed"},
                {"status": "processed"},
            ]
        ),
        "dead_letter_events": _FakeCollection(
            [{"created_at": RECENT}, {"created_at": OLD}, {"created_at": OLD}]
        ),
        "dunning_states": _FakeCollection(
            [
                {"status": "dunned", "terminal_at": RECENT},
                {"status": "dunned", "terminal_at": OLD},
                {"status": "active", "terminal_at": RECENT},
            ]
        ),
        JOB_RUNS_COLLECTION: _FakeCollection(
            [
                {
                    "_id": INVOICE_GENERATION_JOB,
                    "recorded_at": RECENT,
                    "totals": {"created": 12, "skipped_existing": 3, "period": "2026-08"},
                }
            ]
        ),
    }
    collections.update(overrides)
    return _FakeDb(collections)


@pytest.mark.asyncio
async def test_collect_counts_open_webhooks_and_windowed_events() -> None:
    snapshot = await collect_ops_digest(_db(), now=NOW)  # type: ignore[arg-type]

    assert snapshot.webhooks_quarantined == 2
    assert snapshot.webhooks_failed == 1
    # dead letters: 3 in total, 1 inside the 24h window.
    assert snapshot.dead_letter_total == 3
    assert snapshot.dead_letter_recent == 1
    # only the `dunned` state that turned terminal inside the window counts.
    assert snapshot.dunning_terminals_recent == 1
    assert snapshot.lookback_hours == 24
    assert snapshot.errors == []
    assert snapshot.last_invoice_run is not None
    assert snapshot.last_invoice_run["totals"]["created"] == 12
    assert snapshot.has_attention_items is True


@pytest.mark.asyncio
async def test_collect_degrades_when_one_collection_is_unreadable() -> None:
    db = _db(dead_letter_events=_FakeCollection([], fail=True))

    snapshot = await collect_ops_digest(db, now=NOW)  # type: ignore[arg-type]

    # The readable probes still report; the failure is surfaced, not swallowed.
    assert snapshot.webhooks_quarantined == 2
    assert snapshot.dead_letter_total == 0
    assert any("dead_letter_total" in item for item in snapshot.errors)


@pytest.mark.asyncio
async def test_collect_without_a_recorded_invoice_run() -> None:
    db = _db(**{JOB_RUNS_COLLECTION: _FakeCollection([])})

    snapshot = await collect_ops_digest(db, now=NOW)  # type: ignore[arg-type]

    assert snapshot.last_invoice_run is None


@pytest.mark.asyncio
async def test_record_job_run_upserts_totals() -> None:
    runs = _FakeCollection([])
    db = _FakeDb({JOB_RUNS_COLLECTION: runs})

    await record_job_run(db, INVOICE_GENERATION_JOB, {"created": 4})  # type: ignore[arg-type]

    query, update = runs.updates[0]
    assert query == {"_id": INVOICE_GENERATION_JOB}
    assert update["$set"]["totals"] == {"created": 4}


def test_render_flags_attention_and_lists_every_signal() -> None:
    snapshot = OpsDigestSnapshot(
        generated_at=NOW,
        lookback_hours=24,
        webhooks_quarantined=2,
        webhooks_failed=1,
        dead_letter_total=3,
        dead_letter_recent=1,
        dunning_terminals_recent=1,
        last_invoice_run={"recorded_at": RECENT, "totals": {"created": 12}},
    )

    subject, body = render_ops_digest(snapshot)

    assert subject == "Ops digest 2026-08-27 — attention needed"
    assert "Stripe webhooks quarantined" in body
    assert "Dead-letter events" in body
    assert "Dunning terminals" in body
    assert "created: 12" in body
    assert "2026-08-27T05:00:00+00:00" in body


def test_render_all_clear_when_nothing_needs_attention() -> None:
    subject, body = render_ops_digest(
        OpsDigestSnapshot(generated_at=NOW, lookback_hours=24, dead_letter_total=7)
    )

    # A non-zero historical dead-letter total is not itself an alert; only new
    # ones inside the window are.
    assert subject == "Ops digest 2026-08-27 — all clear"
    assert "No quarantined webhooks" in body
    assert "No recorded run." in body


def test_render_escapes_collection_errors() -> None:
    snapshot = OpsDigestSnapshot(
        generated_at=NOW,
        lookback_hours=24,
        errors=["dead_letter_total: <script>alert(1)</script>"],
    )

    _, body = render_ops_digest(snapshot)

    assert "<script>" not in body
    assert "&lt;script&gt;" in body
