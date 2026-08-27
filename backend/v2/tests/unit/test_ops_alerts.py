"""Unit tests for the ops alerting slice (issue #428).

Covers the APScheduler error/missed listener callback and the ops-digest
content assembly. Both use fakes — no Mongo, no Sentry, no Resend.
"""

from __future__ import annotations

import inspect
import logging
from datetime import UTC, datetime, timedelta, timezone
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


def test_job_missed_has_no_exception_so_reports_a_warning_message(
    sentry: _SentrySpy, caplog: pytest.LogCaptureFixture
) -> None:
    event = _FakeJobEvent(job_id="generate_monthly_invoices", code=2**8)

    with caplog.at_level(logging.WARNING):
        ops_alerts.handle_scheduler_job_event(event)

    assert sentry.exceptions == []
    # Warning, not error: a lone misfire on a frequent job is a transient stall.
    assert sentry.messages == [("Scheduler job missed: generate_monthly_invoices", "warning")]
    record = next(r for r in caplog.records if "scheduler_job_missed" in r.getMessage())
    assert record.levelno == logging.WARNING


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


@pytest.mark.parametrize(
    ("consecutive", "expected"),
    [(0, False), (1, True), (2, False), (9, False), (10, True), (11, False), (100, True)],
)
def test_failure_reporting_backs_off(consecutive: int, expected: bool) -> None:
    # A 1s poll loop that keeps failing is one incident, not 86k of them.
    assert ops_alerts.should_report_failure(consecutive) is expected


# --- dispatcher loop guard --------------------------------------------------


@pytest.mark.asyncio
async def test_dispatcher_loop_survives_a_raising_sentry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The last-resort guard must not itself be a way to kill the dispatcher."""
    from backend.v2.shared.events import dispatcher as dispatcher_module

    def _explode(exc: BaseException | None = None) -> bool:
        raise RuntimeError("sentry transport is down")

    monkeypatch.setattr(dispatcher_module, "capture_exception", _explode)

    disp = dispatcher_module.EventDispatcher(object(), poll_interval_seconds=0.01)  # type: ignore[arg-type]

    calls = {"n": 0}

    async def _claim() -> None:
        calls["n"] += 1
        if calls["n"] >= 3:
            disp._stop.set()
        raise RuntimeError("mongo is down")

    monkeypatch.setattr(disp, "_claim_next_event", _claim)

    await disp._run_loop()

    # The loop kept going through both the Mongo failure and the Sentry failure.
    assert calls["n"] >= 3


# --- digest -----------------------------------------------------------------


class _FakeCollection:
    def __init__(
        self,
        docs: list[dict[str, Any]],
        *,
        fail: bool = False,
        aggregate_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self.docs = docs
        self.fail = fail
        self.aggregate_rows = aggregate_rows or []
        self.pipelines: list[list[dict[str, Any]]] = []
        self.updates: list[tuple[dict[str, Any], dict[str, Any]]] = []

    async def count_documents(self, query: dict[str, Any]) -> int:
        if self.fail:
            raise RuntimeError("collection unreadable")
        return sum(1 for doc in self.docs if _matches(doc, query))

    async def estimated_document_count(self) -> int:
        if self.fail:
            raise RuntimeError("collection unreadable")
        return len(self.docs)

    def aggregate(self, pipeline: list[dict[str, Any]]) -> Any:
        self.pipelines.append(pipeline)
        rows = self.aggregate_rows
        fail = self.fail

        async def _iter() -> Any:
            if fail:
                raise RuntimeError("collection unreadable")
            for row in rows:
                yield row

        return _iter()

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        if self.fail:
            raise RuntimeError("collection unreadable")
        return next((doc for doc in self.docs if _matches(doc, query)), None)

    async def update_one(
        self, query: dict[str, Any], update: dict[str, Any], upsert: bool = False
    ) -> None:
        self.updates.append((query, update))
        for doc in self.docs:
            if _matches(doc, query):
                doc.update(update["$set"])
                return
        if upsert:
            self.docs.append({**query, **update["$set"]})


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

# What the single stripe_webhook_events aggregation returns: 5 quarantined
# all-time of which 1 arrived in the window, and 4 failed of which 1 is past due.
WEBHOOK_ROWS = [
    {"_id": "quarantined", "total": 5, "recent": 1, "stale": 0},
    {"_id": "failed", "total": 4, "recent": 4, "stale": 1},
]


def _db(**overrides: _FakeCollection) -> _FakeDb:
    collections: dict[str, _FakeCollection] = {
        "stripe_webhook_events": _FakeCollection([], aggregate_rows=list(WEBHOOK_ROWS)),
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
                    "last_tick_at": RECENT,
                    "totals": {"created": 12, "skipped_existing": 3, "period": "2026-08"},
                }
            ]
        ),
    }
    collections.update(overrides)
    return _FakeDb(collections)


@pytest.mark.asyncio
async def test_collect_splits_webhook_counts_into_actionable_and_informational() -> None:
    snapshot = await collect_ops_digest(_db(), now=NOW)  # type: ignore[arg-type]

    assert snapshot.webhooks_quarantined == 5
    assert snapshot.webhooks_quarantined_recent == 1
    assert snapshot.webhooks_failed == 4
    assert snapshot.webhooks_failed_stale == 1
    # dead letters: 3 in total, 1 inside the 24h window.
    assert snapshot.dead_letter_total == 3
    assert snapshot.dead_letter_recent == 1
    # only the `dunned` state that turned terminal inside the window counts.
    assert snapshot.dunning_terminals_recent == 1
    assert snapshot.lookback_hours == 24
    assert snapshot.errors == []
    assert snapshot.last_invoice_run is not None
    assert snapshot.last_invoice_run["totals"]["created"] == 12


@pytest.mark.asyncio
async def test_webhook_counts_use_one_aggregation_with_the_real_status_literals() -> None:
    db = _db()
    await collect_ops_digest(db, now=NOW)  # type: ignore[arg-type]

    pipelines = db["stripe_webhook_events"].pipelines
    assert len(pipelines) == 1, "both webhook counts must come from a single pass"
    match, group = pipelines[0]
    assert match["$match"]["status"]["$in"] == ["quarantined", "failed"]
    assert group["$group"]["_id"] == "$status"
    # The staleness boundary must be an hour before `now`, not `now`.
    stale_before = group["$group"]["stale"]["$sum"]["$cond"][0]["$lt"][1]
    assert stale_before == NOW - timedelta(hours=1)


@pytest.mark.asyncio
async def test_old_quarantined_events_alone_do_not_pin_attention() -> None:
    db = _db(
        stripe_webhook_events=_FakeCollection(
            [], aggregate_rows=[{"_id": "quarantined", "total": 9, "recent": 0, "stale": 0}]
        ),
        dead_letter_events=_FakeCollection([{"created_at": OLD}]),
        dunning_states=_FakeCollection([]),
    )

    snapshot = await collect_ops_digest(db, now=NOW)  # type: ignore[arg-type]

    assert snapshot.webhooks_quarantined == 9
    assert snapshot.has_attention_items is False


@pytest.mark.asyncio
async def test_failed_events_still_mid_retry_do_not_raise_attention() -> None:
    db = _db(
        stripe_webhook_events=_FakeCollection(
            # 30 failed events, all retrying on schedule — the drain job will
            # clear them within the minute.
            [],
            aggregate_rows=[{"_id": "failed", "total": 30, "recent": 30, "stale": 0}],
        ),
        dead_letter_events=_FakeCollection([]),
        dunning_states=_FakeCollection([]),
    )

    snapshot = await collect_ops_digest(db, now=NOW)  # type: ignore[arg-type]

    assert snapshot.webhooks_failed == 30
    assert snapshot.has_attention_items is False


@pytest.mark.asyncio
async def test_collect_degrades_when_one_collection_is_unreadable() -> None:
    db = _db(dead_letter_events=_FakeCollection([], fail=True))

    snapshot = await collect_ops_digest(db, now=NOW)  # type: ignore[arg-type]

    # The readable probes still report; the failure is surfaced, not swallowed.
    assert snapshot.webhooks_quarantined == 5
    assert snapshot.dead_letter_total == 0
    assert any("dead_letter" in item for item in snapshot.errors)
    assert snapshot.has_attention_items is True


@pytest.mark.asyncio
async def test_collect_without_a_recorded_invoice_run() -> None:
    db = _db(**{JOB_RUNS_COLLECTION: _FakeCollection([])})

    snapshot = await collect_ops_digest(db, now=NOW)  # type: ignore[arg-type]

    assert snapshot.last_invoice_run is None


# --- job-run recording ------------------------------------------------------


@pytest.mark.asyncio
async def test_record_job_run_upserts_totals() -> None:
    runs = _FakeCollection([])
    db = _FakeDb({JOB_RUNS_COLLECTION: runs})

    await record_job_run(db, INVOICE_GENERATION_JOB, {"created": 4})  # type: ignore[arg-type]

    query, update = runs.updates[0]
    assert query == {"_id": INVOICE_GENERATION_JOB}
    assert update["$set"]["totals"] == {"created": 4}
    assert "last_tick_at" in update["$set"]


@pytest.mark.asyncio
async def test_empty_tick_does_not_clobber_the_last_real_run() -> None:
    runs = _FakeCollection([])
    db = _FakeDb({JOB_RUNS_COLLECTION: runs})

    # Day 1: the real generation run.
    await record_job_run(db, INVOICE_GENERATION_JOB, {"academy_count": 2, "created": 12})  # type: ignore[arg-type]
    # Day 2..30: the daily tick fires but no academy's billing_day matches.
    await record_job_run(  # type: ignore[arg-type]
        db,
        INVOICE_GENERATION_JOB,
        {"academy_count": 0, "created": 0},
        meaningful=False,
    )

    snapshot = await collect_ops_digest(db, now=NOW)  # type: ignore[arg-type]
    assert snapshot.last_invoice_run is not None
    assert snapshot.last_invoice_run["totals"] == {"academy_count": 2, "created": 12}
    # The heartbeat still moved, so a job that stopped ticking is still visible.
    assert snapshot.last_invoice_tick_at is not None


# --- rendering --------------------------------------------------------------


def test_render_flags_attention_and_lists_every_signal() -> None:
    snapshot = OpsDigestSnapshot(
        generated_at=NOW,
        lookback_hours=24,
        webhooks_quarantined=5,
        webhooks_quarantined_recent=1,
        webhooks_failed=4,
        webhooks_failed_stale=1,
        dead_letter_total=3,
        dead_letter_recent=1,
        dunning_terminals_recent=1,
        last_invoice_run={"recorded_at": RECENT, "totals": {"created": 12}},
    )

    subject, body = render_ops_digest(snapshot)

    assert subject == "Ops digest 2026-08-27 — attention needed"
    assert "Stripe webhooks quarantined" in body
    # The all-time total stays visible even though only the window drives the flag.
    assert ">5<" in body
    assert "Dead-letter events" in body
    assert "Dunning terminals" in body
    assert "created: 12" in body
    assert "2026-08-27T05:00:00+00:00" in body


def test_render_stamps_the_date_it_is_given_not_utc() -> None:
    # main.py passes datetime.now(scheduler.timezone); a 07:00 local send in a
    # UTC+ zone must not be labelled with the previous UTC day.
    tokyo_morning = datetime(2026, 8, 27, 7, 0, tzinfo=timezone(timedelta(hours=9)))

    subject, _ = render_ops_digest(OpsDigestSnapshot(generated_at=tokyo_morning, lookback_hours=24))

    assert "2026-08-27" in subject


def test_render_all_clear_when_nothing_needs_attention() -> None:
    subject, body = render_ops_digest(
        OpsDigestSnapshot(generated_at=NOW, lookback_hours=24, dead_letter_total=7)
    )

    # A non-zero historical dead-letter total is not itself an alert; only new
    # ones inside the window are.
    assert subject == "Ops digest 2026-08-27 — all clear"
    assert "Nothing new needs attention" in body
    assert "No recorded run." in body


def test_render_escapes_collection_errors() -> None:
    snapshot = OpsDigestSnapshot(
        generated_at=NOW,
        lookback_hours=24,
        errors=["dead_letter: <script>alert(1)</script>"],
    )

    _, body = render_ops_digest(snapshot)

    assert "<script>" not in body
    assert "&lt;script&gt;" in body


# --- main.py integration seam ----------------------------------------------


def test_invoice_job_records_a_heartbeat_only_when_nothing_was_generated() -> None:
    """Issue #428 x #440: the ops_job_runs write must stay gated on the totals
    returned by _run_monthly_invoice_generation.

    `academy_count` counts only academies that actually attempted generation
    (`ran_any`), so it is the right "meaningful" bar. If a refactor ever drops
    the gate, ~29 heartbeat ticks a month would overwrite the last real run's
    counts with zeros and the digest would report nothing but zeros forever.

    Issue #430 widened the bar — but only to other real work. The auto-email
    pass runs on every tick (it is the retry path for a failed delivery), so a
    tick that emailed or failed to email must also store its counts, or a
    month-long email outage would be invisible on the 29 days that generated
    nothing. A tick that did neither still writes a heartbeat only.
    """
    from backend.v2.main import _lifespan

    body = inspect.getsource(_lifespan).split("_generate_monthly_invoices_body", 2)[2]
    call = body.split("record_job_run(", 1)[1].split("        )", 1)[0]

    assert 'totals["academy_count"]' in call
    assert 'totals["invoices_emailed"]' in call
    assert 'totals["invoice_emails_failed"]' in call
    # Still gated: an idle tick must not overwrite the last real run's counts.
    assert "meaningful=bool(" in call
    assert "meaningful=True" not in call
    # The stored record must use #440's `created_count` naming so the email and
    # the structured log line agree.
    assert 'record["created_count"] = totals["created"]' in body
