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
    JOB_STALE_AFTER,
    OpsDigestSnapshot,
    collect_ops_digest,
    record_job_run,
    render_ops_digest,
    seed_job_heartbeats,
    stale_jobs,
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

    def find(self, query: dict[str, Any], _projection: dict[str, Any] | None = None) -> Any:
        docs = self.docs
        fail = self.fail

        async def _iter() -> Any:
            if fail:
                raise RuntimeError("collection unreadable")
            for doc in docs:
                if _matches(doc, query):
                    yield doc

        return _iter()

    async def update_one(
        self, query: dict[str, Any], update: dict[str, Any], upsert: bool = False
    ) -> None:
        self.updates.append((query, update))
        for doc in self.docs:
            if _matches(doc, query):
                doc.update(update.get("$set", {}))
                return
        if upsert:
            self.docs.append({**query, **update.get("$set", {}), **update.get("$setOnInsert", {})})


def _matches(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        actual = doc.get(key)
        if isinstance(expected, dict) and "$gte" in expected:
            if actual is None or actual < expected["$gte"]:
                return False
        elif isinstance(expected, dict) and "$ne" in expected:
            # Mongo's $ne matches missing fields too, which is exactly why the
            # digest queries use it — rows predating a field must still count.
            if actual == expected["$ne"]:
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
# Every scheduled job ticked a minute ago: inside even the tightest threshold.
FRESH_TICKS = {job_id: NOW - timedelta(minutes=1) for job_id in JOB_STALE_AFTER}

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
                },
                *(
                    {"_id": job_id, "last_tick_at": tick}
                    for job_id, tick in FRESH_TICKS.items()
                    if job_id != INVOICE_GENERATION_JOB
                ),
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
        OpsDigestSnapshot(
            generated_at=NOW, lookback_hours=24, dead_letter_total=7, job_ticks=FRESH_TICKS
        )
    )

    # A non-zero historical dead-letter total is not itself an alert; only new
    # ones inside the window are.
    assert subject == "Ops digest 2026-08-27 — all clear"
    assert "Nothing new needs attention" in body
    assert "No recorded run." in body
    assert f"All {len(JOB_STALE_AFTER)} scheduled jobs reported a heartbeat" in body


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


# ---------------------------------------------------------------------------
# Failed digest sends (issue #435)
# ---------------------------------------------------------------------------


def test_digest_attempt_ceiling_matches_the_domain() -> None:
    """``shared/`` may not import a bounded context, so the retry ceiling is
    duplicated in ops_digest. If the two ever drift, the digest silently counts
    the wrong rows as "no retries left" — this pins them together."""
    from backend.v2.contexts.communications.domain.models import MAX_DIGEST_SEND_ATTEMPTS
    from backend.v2.shared.observability.ops_digest import DIGEST_ATTEMPT_CEILING

    assert DIGEST_ATTEMPT_CEILING == MAX_DIGEST_SEND_ATTEMPTS


@pytest.mark.asyncio
async def test_digest_send_failures_split_retryable_from_exhausted() -> None:
    """Both digest collections are counted, and only rows that used every
    attempt are the actionable number."""
    snapshot = await collect_ops_digest(
        _db(  # type: ignore[arg-type]
            coach_digest_sends=_FakeCollection(
                [
                    {"status": "failed", "created_at": RECENT, "attempt_count": 3},
                    {"status": "failed", "created_at": RECENT, "attempt_count": 1},
                    {"status": "sent", "created_at": RECENT, "attempt_count": 1},
                    # Outside the 24h window.
                    {"status": "failed", "created_at": OLD, "attempt_count": 3},
                ]
            ),
            parent_digest_sends=_FakeCollection(
                [{"status": "failed", "created_at": RECENT, "attempt_count": 3}]
            ),
        ),
        now=NOW,
    )

    assert snapshot.digest_sends_failed == 3
    assert snapshot.digest_sends_failed_exhausted == 2
    assert snapshot.has_attention_items


@pytest.mark.asyncio
async def test_retryable_digest_failures_alone_do_not_raise_attention() -> None:
    """A failure with retries left almost always lands on the next hourly tick.
    Flagging it would make "attention needed" mean nothing."""
    snapshot = await collect_ops_digest(
        _db(  # type: ignore[arg-type]
            stripe_webhook_events=_FakeCollection([], aggregate_rows=[]),
            dead_letter_events=_FakeCollection([]),
            dunning_states=_FakeCollection([]),
            coach_digest_sends=_FakeCollection(
                [{"status": "failed", "created_at": RECENT, "attempt_count": 1}]
            ),
        ),
        now=NOW,
    )

    assert snapshot.digest_sends_failed == 1
    assert snapshot.digest_sends_failed_exhausted == 0
    assert not snapshot.has_attention_items
    subject, body = render_ops_digest(snapshot)
    assert "all clear" in subject
    # Still reported in the body — informational, not actionable.
    assert "Digest sends failed" in body


@pytest.mark.asyncio
async def test_unreachable_recipients_do_not_pin_the_attention_flag() -> None:
    """A coach with no e-mail address fails every day forever. Counting it as a
    lost digest would make "attention needed" permanent and therefore useless —
    it stays in the informational total only."""
    snapshot = await collect_ops_digest(
        _db(  # type: ignore[arg-type]
            stripe_webhook_events=_FakeCollection([], aggregate_rows=[]),
            dead_letter_events=_FakeCollection([]),
            dunning_states=_FakeCollection([]),
            coach_digest_sends=_FakeCollection(
                [
                    {
                        "status": "failed",
                        "created_at": RECENT,
                        "attempt_count": 3,
                        "retryable": False,
                    }
                ]
            ),
        ),
        now=NOW,
    )

    assert snapshot.digest_sends_failed == 1
    assert snapshot.digest_sends_failed_exhausted == 0
    assert not snapshot.has_attention_items


# ---------------------------------------------------------------------------
# Dead-man switch: stale scheduled jobs
# ---------------------------------------------------------------------------


def test_fresh_jobs_are_not_stale() -> None:
    assert stale_jobs(FRESH_TICKS, NOW) == []


def test_a_job_just_inside_its_threshold_is_not_stale_but_past_it_is() -> None:
    ticks = dict(FRESH_TICKS)
    ticks["process_stripe_webhook_events"] = NOW - JOB_STALE_AFTER["process_stripe_webhook_events"]
    assert stale_jobs(ticks, NOW) == []

    ticks["process_stripe_webhook_events"] -= timedelta(seconds=1)
    (stale,) = stale_jobs(ticks, NOW)
    assert stale.job_id == "process_stripe_webhook_events"
    assert stale.expected_within == timedelta(minutes=5)
    assert stale.last_tick_at == ticks["process_stripe_webhook_events"]
    assert stale.age == timedelta(minutes=5, seconds=1)


def test_each_job_uses_its_own_threshold() -> None:
    """A 2h-old tick is stale for the 60s webhook drain and fine for a daily cron."""
    ticks = {job_id: NOW - timedelta(hours=2) for job_id in JOB_STALE_AFTER}

    stale_ids = {job.job_id for job in stale_jobs(ticks, NOW)}

    assert stale_ids == {"process_stripe_webhook_events", "reconcile_stripe_payment_intents"}


def test_a_job_with_no_heartbeat_is_stale() -> None:
    """The job that never fired is the exact case the switch exists for."""
    ticks = dict(FRESH_TICKS)
    del ticks["send_ops_digest"]

    (stale,) = stale_jobs(ticks, NOW)

    assert stale.job_id == "send_ops_digest"
    assert stale.last_tick_at is None
    assert stale.age is None


def test_naive_mongo_ticks_are_read_as_utc() -> None:
    ticks = dict(FRESH_TICKS)
    ticks["send_ops_digest"] = (NOW - timedelta(minutes=1)).replace(tzinfo=None)
    assert stale_jobs(ticks, NOW) == []


def test_stale_jobs_are_listed_in_table_order() -> None:
    assert [job.job_id for job in stale_jobs({}, NOW)] == list(JOB_STALE_AFTER)


def test_a_stale_job_alone_raises_the_attention_flag() -> None:
    ticks = dict(FRESH_TICKS)
    ticks["generate_monthly_invoices"] = NOW - timedelta(hours=27)
    snapshot = OpsDigestSnapshot(generated_at=NOW, lookback_hours=24, job_ticks=ticks)

    assert snapshot.has_attention_items is True

    subject, body = render_ops_digest(snapshot)
    assert subject == "Ops digest 2026-08-27 — attention needed"
    assert "Scheduled jobs NOT ticking (1)" in body
    assert "<strong>generate_monthly_invoices</strong>" in body
    assert "expected within 26h" in body
    assert "2026-08-26T04:00:00+00:00" in body
    assert "(27h ago)" in body
    assert "Nothing new needs attention" not in body


def test_a_never_recorded_job_is_rendered_as_such() -> None:
    ticks = dict(FRESH_TICKS)
    del ticks["expire_makeup_requests"]

    _subject, body = render_ops_digest(
        OpsDigestSnapshot(generated_at=NOW, lookback_hours=24, job_ticks=ticks)
    )

    assert "<strong>expire_makeup_requests</strong>" in body
    assert "last heartbeat never recorded" in body


@pytest.mark.asyncio
async def test_first_digest_after_a_deploy_lists_every_unticked_job_without_the_seed() -> None:
    """Prod before this branch: only the invoice generator ever wrote a heartbeat."""
    runs = _FakeCollection([{"_id": INVOICE_GENERATION_JOB, "last_tick_at": RECENT}])
    snapshot = await collect_ops_digest(_db(**{JOB_RUNS_COLLECTION: runs}), now=NOW)  # type: ignore[arg-type]

    assert {job.job_id for job in snapshot.stale_jobs} == set(JOB_STALE_AFTER) - {
        INVOICE_GENERATION_JOB
    }
    assert "send_ops_digest" in {job.job_id for job in snapshot.stale_jobs}
    assert snapshot.has_attention_items


@pytest.mark.asyncio
async def test_boot_seed_stops_the_first_digest_flagging_itself() -> None:
    runs = _FakeCollection([{"_id": INVOICE_GENERATION_JOB, "last_tick_at": RECENT}])
    db = _db(**{JOB_RUNS_COLLECTION: runs})
    boot = NOW - timedelta(hours=3)  # deployed at 04:00, digest fires at 07:00

    await seed_job_heartbeats(db, now=boot)  # type: ignore[arg-type]
    # Only $setOnInsert, so nothing here can move a real heartbeat.
    assert all(set(update) == {"$setOnInsert"} for _, update in runs.updates)
    assert len(runs.updates) == len(JOB_STALE_AFTER)
    # By 07:00 the interval jobs have ticked for real; the dailies (02:00,
    # 02:30, 03:00 crons) and the digest itself have not fired since boot.
    for doc in runs.docs:
        if doc["_id"] in {"process_stripe_webhook_events", "reconcile_stripe_payment_intents"}:
            doc["last_tick_at"] = NOW - timedelta(minutes=1)

    snapshot = await collect_ops_digest(db, now=NOW)  # type: ignore[arg-type]

    assert snapshot.stale_jobs == []


@pytest.mark.asyncio
async def test_boot_seed_never_moves_an_existing_heartbeat() -> None:
    """A job that stopped ticking before the restart must stay stale."""
    runs = _FakeCollection([{"_id": "process_dunning_retries", "last_tick_at": OLD}])
    db = _db(**{JOB_RUNS_COLLECTION: runs})

    await seed_job_heartbeats(db, now=NOW)  # type: ignore[arg-type]
    snapshot = await collect_ops_digest(db, now=NOW)  # type: ignore[arg-type]

    assert [job.job_id for job in snapshot.stale_jobs] == ["process_dunning_retries"]
    assert snapshot.stale_jobs[0].last_tick_at == OLD


@pytest.mark.asyncio
async def test_seeded_jobs_go_stale_once_a_full_window_passes_without_a_tick() -> None:
    runs = _FakeCollection([])
    db = _db(**{JOB_RUNS_COLLECTION: runs})
    await seed_job_heartbeats(db, now=NOW - timedelta(minutes=6))  # type: ignore[arg-type]

    snapshot = await collect_ops_digest(db, now=NOW)  # type: ignore[arg-type]

    # The 60s webhook drain (5 min window) is the only one past its window.
    assert [job.job_id for job in snapshot.stale_jobs] == ["process_stripe_webhook_events"]


@pytest.mark.asyncio
async def test_collect_reads_every_job_heartbeat() -> None:
    snapshot = await collect_ops_digest(_db(), now=NOW)  # type: ignore[arg-type]

    assert snapshot.errors == []
    assert set(snapshot.job_ticks) == set(JOB_STALE_AFTER)
    assert snapshot.job_ticks[INVOICE_GENERATION_JOB] == RECENT
    assert snapshot.stale_jobs == []


@pytest.mark.asyncio
async def test_collect_flags_a_job_that_stopped_ticking() -> None:
    docs = [{"_id": job_id, "last_tick_at": tick} for job_id, tick in FRESH_TICKS.items()]
    docs = [doc for doc in docs if doc["_id"] != "process_dunning_retries"]
    docs.append({"_id": "process_dunning_retries", "last_tick_at": NOW - timedelta(hours=4)})

    snapshot = await collect_ops_digest(  # type: ignore[arg-type]
        _db(**{JOB_RUNS_COLLECTION: _FakeCollection(docs)}), now=NOW
    )

    assert [job.job_id for job in snapshot.stale_jobs] == ["process_dunning_retries"]
    assert snapshot.has_attention_items is True


# ---------------------------------------------------------------------------
# Sentry Crons check-ins (opt-in per job)
# ---------------------------------------------------------------------------


class _CronsSpy:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail = fail

    def capture_checkin(self, **kwargs: Any) -> str:
        if self.fail:
            raise RuntimeError("transport down")
        self.calls.append(kwargs)
        return kwargs.get("check_in_id") or "chk-1"


class _CronSentry:
    def __init__(self, *, fail: bool = False) -> None:
        self.crons = _CronsSpy(fail=fail)


class _CronSettings:
    def __init__(self, jobs: tuple[str, ...] = ("generate_monthly_invoices",)) -> None:
        self.sentry_cron_jobs = jobs
        self.scheduler_tz = "America/Chicago"


SCHEDULE = {"schedule": {"type": "crontab", "value": "0 3 * * *"}, "checkin_margin": 60}


@pytest.mark.asyncio
async def test_cron_checkin_is_a_no_op_without_sentry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ops_alerts, "_active_sentry", lambda: None)
    ran = False

    async with ops_alerts.cron_checkin(
        "generate_monthly_invoices", schedule=SCHEDULE, settings=_CronSettings()
    ):
        ran = True

    assert ran


@pytest.mark.asyncio
async def test_cron_checkin_is_a_no_op_for_jobs_outside_the_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentry = _CronSentry()
    monkeypatch.setattr(ops_alerts, "_active_sentry", lambda: sentry)

    async with ops_alerts.cron_checkin(
        "send_ops_digest", schedule=SCHEDULE, settings=_CronSettings()
    ):
        pass

    assert sentry.crons.calls == []


@pytest.mark.asyncio
async def test_cron_checkin_records_in_progress_then_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    sentry = _CronSentry()
    monkeypatch.setattr(ops_alerts, "_active_sentry", lambda: sentry)

    async with ops_alerts.cron_checkin(
        "generate_monthly_invoices", schedule=SCHEDULE, settings=_CronSettings()
    ):
        assert [call["status"] for call in sentry.crons.calls] == ["in_progress"]

    start, done = sentry.crons.calls
    assert start["monitor_slug"] == "generate_monthly_invoices"
    assert start["check_in_id"] is None
    assert start["monitor_config"] == {**SCHEDULE, "timezone": "America/Chicago"}
    assert done["status"] == "ok"
    assert done["check_in_id"] == "chk-1"
    assert done["monitor_slug"] == "generate_monthly_invoices"
    assert done["duration"] >= 0
    assert done["monitor_config"] == start["monitor_config"]


@pytest.mark.asyncio
async def test_cron_checkin_records_error_and_re_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    sentry = _CronSentry()
    monkeypatch.setattr(ops_alerts, "_active_sentry", lambda: sentry)

    with pytest.raises(RuntimeError, match="boom"):
        async with ops_alerts.cron_checkin(
            "generate_monthly_invoices", schedule=SCHEDULE, settings=_CronSettings()
        ):
            raise RuntimeError("boom")

    assert [call["status"] for call in sentry.crons.calls] == ["in_progress", "error"]
    assert sentry.crons.calls[1]["check_in_id"] == "chk-1"


@pytest.mark.asyncio
async def test_cron_checkin_failure_never_reaches_the_job(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The switch must not be able to break the job it watches."""
    monkeypatch.setattr(ops_alerts, "_active_sentry", lambda: _CronSentry(fail=True))
    ran = False

    with caplog.at_level(logging.WARNING, logger="backend.v2.shared.observability.ops_alerts"):
        async with ops_alerts.cron_checkin(
            "generate_monthly_invoices", schedule=SCHEDULE, settings=_CronSettings()
        ):
            ran = True

    assert ran
    assert "sentry_cron_checkin_failed" in caplog.text


def test_sentry_cron_jobs_setting_parses_a_comma_separated_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.v2.shared.config.settings import Settings

    monkeypatch.delenv("V2_SENTRY_CRON_JOBS", raising=False)
    monkeypatch.delenv("SENTRY_CRON_JOBS", raising=False)
    assert Settings().sentry_cron_jobs == ("generate_monthly_invoices",)

    monkeypatch.setenv("SENTRY_CRON_JOBS", "generate_monthly_invoices, send_ops_digest,")
    assert Settings().sentry_cron_jobs == ("generate_monthly_invoices", "send_ops_digest")

    monkeypatch.setenv("V2_SENTRY_CRON_JOBS", "")
    assert Settings().sentry_cron_jobs == ()
