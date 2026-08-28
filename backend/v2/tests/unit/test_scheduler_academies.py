from __future__ import annotations

import inspect
from datetime import datetime

import pytest
from pymongo.errors import DuplicateKeyError

from backend.v2.main import (
    _due_periods,
    _lifespan,
    _previous_period,
    _run_monthly_invoice_generation,
    _scheduler_academy_ids,
)
from backend.v2.shared.tenancy.context import current_academy_id


class _FakeAcademyRepo:
    def __init__(self, docs: list[dict[str, object]]) -> None:
        self._ids = [str(doc.get("academy_id") or "") for doc in docs]

    async def list_ids(self) -> list[str]:
        return self._ids


@pytest.mark.asyncio
async def test_scheduler_academy_ids_are_unique_and_include_default() -> None:
    academies = _FakeAcademyRepo(
        [
            {"academy_id": "academy-a"},
            {"academy_id": "academy-b"},
            {"academy_id": "academy-a"},
            {"academy_id": ""},
        ]
    )

    assert await _scheduler_academy_ids(academies, "default-academy") == [
        "academy-a",
        "academy-b",
        "default-academy",
    ]


@pytest.mark.asyncio
async def test_scheduler_academy_ids_uses_configured_runtime_fallback() -> None:
    academies = _FakeAcademyRepo(
        [
            {"academy_id": "academy-a"},
            {"academy_id": "primary-academy"},
        ]
    )

    assert await _scheduler_academy_ids(academies, "primary-academy") == [
        "academy-a",
        "primary-academy",
    ]


def test_scheduler_registers_stripe_payment_intent_reconciliation_job() -> None:
    source = inspect.getsource(_lifespan)

    assert "_reconcile_stripe_payment_intents" in source
    assert 'id="reconcile_stripe_payment_intents"' in source


def test_scheduler_registers_dunning_retry_job() -> None:
    source = inspect.getsource(_lifespan)

    assert "_process_dunning_retries" in source
    assert 'id="process_dunning_retries"' in source


def test_scheduler_registers_monthly_invoice_generation_job() -> None:
    """Issue #288: the 2026-07-01 miss was caused by nothing *generating*
    invoices. Without this registration the whole feature is inert, which is
    exactly the failure mode that shipped."""
    source = inspect.getsource(_lifespan)

    assert "_generate_monthly_invoices" in source
    assert 'id="generate_monthly_invoices"' in source


def test_monthly_invoice_job_runs_daily_and_gates_on_billing_day() -> None:
    """The cron fires every day; the per-academy billing_day decides who is
    generated for. A monthly cron would silently skip any academy configured
    for a day other than the cron's own."""
    source = inspect.getsource(_lifespan)
    job = source.split("_generate_monthly_invoices,", 1)[1].split(")", 1)[0]

    assert '"cron"' in job
    assert "day=" not in job  # daily tick, not a fixed day-of-month
    # Issue #431: the gate is "billing_day has passed", not an exact-day match.
    gate = inspect.getsource(_due_periods)
    assert "if now.day >= billing_day:" in gate
    assert "billing_day != now.day" not in gate


def test_monthly_invoice_job_holds_a_distributed_lease() -> None:
    """Two Fly machines running generation concurrently would race on the same
    invoices; the lease is what keeps exactly one machine generating."""
    source = inspect.getsource(_lifespan)

    assert 'job_lease(\n            db, "generate_monthly_invoices"' in source


# --- issue #431: monthly generation catch-up window -------------------------


class _FakeGenerationRuns:
    """Minimal stand-in for the ``billing_generation_runs`` collection."""

    def __init__(self) -> None:
        self.docs: list[dict[str, object]] = []
        self.write_error: Exception | None = None

    async def find_one(
        self,
        query: dict[str, object],
        _projection: dict[str, int] | None = None,
    ) -> dict[str, object] | None:
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return doc
        return None

    async def update_one(
        self,
        query: dict[str, object],
        update: dict[str, dict[str, object]],
        upsert: bool = False,
    ) -> None:
        if self.write_error is not None:
            raise self.write_error
        existing = await self.find_one(query)
        if existing is None:
            assert upsert
            existing = dict(update.get("$setOnInsert") or {})
            self.docs.append(existing)
        existing.update(update.get("$set") or {})

    def periods_for(self, academy_id: str) -> list[str]:
        return [str(doc["period"]) for doc in self.docs if doc.get("academy_id") == academy_id]


class _FakeDb:
    def __init__(self) -> None:
        self.generation_runs = _FakeGenerationRuns()

    def __getitem__(self, name: str) -> _FakeGenerationRuns:
        assert name == "billing_generation_runs", name
        return self.generation_runs


class _FakeSettings:
    def __init__(self, billing_day: int) -> None:
        self.billing_day = billing_day


class _FakeResult:
    def __init__(
        self,
        created: int = 0,
        skipped_existing: int = 0,
        failed_repair: int = 0,
    ) -> None:
        self.created = created
        self.skipped_existing = skipped_existing
        self.failed_repair = failed_repair


def _settings_getter(by_academy: dict[str, object]):
    async def _get() -> object:
        value = by_academy[current_academy_id()]
        if isinstance(value, Exception):
            raise value
        return value

    return _get


def _seed_history(db: _FakeDb, academy_id: str, *periods: str) -> None:
    """Pretend the academy already generated these periods."""
    for period in periods:
        db.generation_runs.docs.append({"academy_id": academy_id, "period": period})


def test_previous_period_wraps_the_year() -> None:
    assert _previous_period("2026-09") == "2026-08"
    assert _previous_period("2026-01") == "2025-12"
    assert _previous_period("2026-11") == "2026-10"


@pytest.mark.asyncio
async def test_catch_up_generates_when_billing_day_already_passed() -> None:
    """The 03:00 run on billing_day failed (nothing recorded). Two days later
    the daily tick must still invoice the month instead of skipping it."""
    db = _FakeDb()
    _seed_history(db, "academy-a", "2026-08")
    calls: list[str] = []

    async def _generate(period: str) -> _FakeResult:
        calls.append(period)
        return _FakeResult(created=4)

    totals = await _run_monthly_invoice_generation(
        db=db,
        academy_ids=["academy-a"],
        get_billing_settings=_settings_getter({"academy-a": _FakeSettings(5)}),
        generate=_generate,
        now=datetime(2026, 9, 7, 3, 0),
    )

    assert calls == ["2026-09"]
    assert totals["created"] == 4
    assert totals["catch_up_run_count"] == 1
    assert db.generation_runs.periods_for("academy-a") == ["2026-08", "2026-09"]


@pytest.mark.asyncio
async def test_no_regeneration_the_day_after_a_successful_run() -> None:
    """Without the run record the catch-up window would re-walk every academy
    every day for the rest of the month."""
    db = _FakeDb()
    _seed_history(db, "academy-a", "2026-08")
    calls: list[str] = []

    async def _generate(period: str) -> _FakeResult:
        calls.append(period)
        return _FakeResult(created=4)

    settings = _settings_getter({"academy-a": _FakeSettings(5)})
    await _run_monthly_invoice_generation(
        db=db,
        academy_ids=["academy-a"],
        get_billing_settings=settings,
        generate=_generate,
        now=datetime(2026, 9, 5, 3, 0),
    )
    totals = await _run_monthly_invoice_generation(
        db=db,
        academy_ids=["academy-a"],
        get_billing_settings=settings,
        generate=_generate,
        now=datetime(2026, 9, 6, 3, 0),
    )

    assert calls == ["2026-09"]  # generated once, not twice
    assert totals["academy_count"] == 0
    assert db.generation_runs.periods_for("academy-a") == ["2026-08", "2026-09"]


@pytest.mark.asyncio
async def test_before_billing_day_nothing_is_generated() -> None:
    db = _FakeDb()
    _seed_history(db, "academy-a", "2026-08")
    calls: list[str] = []

    async def _generate(period: str) -> _FakeResult:
        calls.append(period)
        return _FakeResult(created=1)

    totals = await _run_monthly_invoice_generation(
        db=db,
        academy_ids=["academy-a"],
        get_billing_settings=_settings_getter({"academy-a": _FakeSettings(5)}),
        generate=_generate,
        now=datetime(2026, 9, 4, 3, 0),
    )

    assert calls == []
    assert totals["academy_count"] == 0
    assert db.generation_runs.periods_for("academy-a") == ["2026-08"]


@pytest.mark.asyncio
async def test_unreadable_billing_settings_falls_back_to_the_default_day() -> None:
    """The billing context's rule is that settings "must never block the
    monthly run" — an unreadable doc must degrade to the default billing_day,
    not turn into a permanent silent skip for that academy."""
    db = _FakeDb()
    _seed_history(db, "academy-a", "2026-08")
    calls: list[str] = []

    async def _generate(period: str) -> _FakeResult:
        calls.append(period)
        return _FakeResult(created=2)

    totals = await _run_monthly_invoice_generation(
        db=db,
        academy_ids=["academy-a"],
        get_billing_settings=_settings_getter(
            {"academy-a": RuntimeError("billing_settings unreadable")}
        ),
        generate=_generate,
        # Default billing_day is 1, so the 3rd is past it.
        now=datetime(2026, 9, 3, 3, 0),
    )

    assert calls == ["2026-09"]
    assert totals["created"] == 2


@pytest.mark.asyncio
async def test_one_academys_settings_failure_does_not_abort_the_rest() -> None:
    """The settings read moved inside the per-academy try (issue #431): a
    single unreadable billing_settings document used to abort the whole run,
    silently skipping every academy after it."""
    db = _FakeDb()
    _seed_history(db, "academy-bad", "2026-08")
    _seed_history(db, "academy-good", "2026-08")
    generated: list[str] = []

    async def _generate(period: str) -> _FakeResult:
        generated.append(current_academy_id())
        return _FakeResult(created=2)

    totals = await _run_monthly_invoice_generation(
        db=db,
        academy_ids=["academy-bad", "academy-good"],
        get_billing_settings=_settings_getter(
            {
                "academy-bad": RuntimeError("billing_settings unreadable"),
                "academy-good": _FakeSettings(1),
            }
        ),
        generate=_generate,
        now=datetime(2026, 9, 3, 3, 0),
    )

    assert generated == ["academy-bad", "academy-good"]
    assert totals["academy_count"] == 2
    assert totals["created"] == 4


@pytest.mark.asyncio
async def test_one_academys_generation_failure_does_not_abort_the_rest() -> None:
    db = _FakeDb()
    _seed_history(db, "academy-bad", "2026-08")
    _seed_history(db, "academy-good", "2026-08")
    attempted: list[str] = []

    async def _generate(period: str) -> _FakeResult:
        academy_id = current_academy_id()
        attempted.append(academy_id)
        if academy_id == "academy-bad":
            raise RuntimeError("mongo blip")
        return _FakeResult(created=2)

    totals = await _run_monthly_invoice_generation(
        db=db,
        academy_ids=["academy-bad", "academy-good"],
        get_billing_settings=_settings_getter(
            {"academy-bad": _FakeSettings(1), "academy-good": _FakeSettings(1)}
        ),
        generate=_generate,
        now=datetime(2026, 9, 3, 3, 0),
    )

    assert attempted == ["academy-bad", "academy-good"]
    assert totals["academy_count"] == 1
    assert totals["created"] == 2
    # The failed academy leaves no record for 2026-09, so the next tick retries.
    assert db.generation_runs.periods_for("academy-bad") == ["2026-08"]


@pytest.mark.asyncio
async def test_generation_failure_leaves_no_record_so_the_next_tick_retries() -> None:
    db = _FakeDb()
    _seed_history(db, "academy-a", "2026-08")
    attempts: list[str] = []

    async def _flaky(period: str) -> _FakeResult:
        attempts.append(period)
        if len(attempts) == 1:
            raise RuntimeError("mongo blip")
        return _FakeResult(created=3)

    settings = _settings_getter({"academy-a": _FakeSettings(1)})
    first = await _run_monthly_invoice_generation(
        db=db,
        academy_ids=["academy-a"],
        get_billing_settings=settings,
        generate=_flaky,
        now=datetime(2026, 9, 1, 3, 0),
    )
    assert first["academy_count"] == 0
    assert db.generation_runs.periods_for("academy-a") == ["2026-08"]

    second = await _run_monthly_invoice_generation(
        db=db,
        academy_ids=["academy-a"],
        get_billing_settings=settings,
        generate=_flaky,
        now=datetime(2026, 9, 2, 3, 0),
    )

    assert attempts == ["2026-09", "2026-09"]
    assert second["created"] == 3
    assert second["catch_up_run_count"] == 1


# --- partial failures must not record success -------------------------------


@pytest.mark.asyncio
async def test_partial_run_with_failed_repair_is_not_recorded() -> None:
    """generate_monthly_payments swallows per-enrollment repair failures and
    still returns normally. Recording success there would switch off the daily
    retry for exactly the enrollments that still need it."""
    db = _FakeDb()
    _seed_history(db, "academy-a", "2026-08")
    attempts: list[str] = []

    async def _partial_then_clean(period: str) -> _FakeResult:
        attempts.append(period)
        if len(attempts) == 1:
            return _FakeResult(created=12, failed_repair=1)
        return _FakeResult(created=1)

    settings = _settings_getter({"academy-a": _FakeSettings(1)})
    first = await _run_monthly_invoice_generation(
        db=db,
        academy_ids=["academy-a"],
        get_billing_settings=settings,
        generate=_partial_then_clean,
        now=datetime(2026, 9, 1, 3, 0),
    )

    # The run counted (invoices were created) but was NOT recorded.
    assert first["created"] == 12
    assert first["failed_repair"] == 1
    assert first["partial_run_count"] == 1
    assert db.generation_runs.periods_for("academy-a") == ["2026-08"]

    second = await _run_monthly_invoice_generation(
        db=db,
        academy_ids=["academy-a"],
        get_billing_settings=settings,
        generate=_partial_then_clean,
        now=datetime(2026, 9, 2, 3, 0),
    )

    # Retried, and the clean re-run finally records the period.
    assert attempts == ["2026-09", "2026-09"]
    assert second["partial_run_count"] == 0
    assert db.generation_runs.periods_for("academy-a") == ["2026-08", "2026-09"]


# --- run-record write failures are not generation failures ------------------


@pytest.mark.asyncio
async def test_duplicate_key_on_the_run_record_is_benign() -> None:
    """Two machines can race the 0151 unique index across a lease handover.
    The loser must not report a generation failure for a run that created
    invoices, nor drop the academy from the summary."""
    db = _FakeDb()
    _seed_history(db, "academy-a", "2026-08")
    db.generation_runs.write_error = DuplicateKeyError("racing machine won")

    async def _generate(period: str) -> _FakeResult:
        return _FakeResult(created=5)

    totals = await _run_monthly_invoice_generation(
        db=db,
        academy_ids=["academy-a"],
        get_billing_settings=_settings_getter({"academy-a": _FakeSettings(1)}),
        generate=_generate,
        now=datetime(2026, 9, 1, 3, 0),
    )

    assert totals["academy_count"] == 1
    assert totals["created"] == 5


@pytest.mark.asyncio
async def test_run_record_write_blip_does_not_mask_a_successful_generation() -> None:
    db = _FakeDb()
    _seed_history(db, "academy-a", "2026-08")
    db.generation_runs.write_error = RuntimeError("write blip")

    async def _generate(period: str) -> _FakeResult:
        return _FakeResult(created=5)

    totals = await _run_monthly_invoice_generation(
        db=db,
        academy_ids=["academy-a"],
        get_billing_settings=_settings_getter({"academy-a": _FakeSettings(1)}),
        generate=_generate,
        now=datetime(2026, 9, 1, 3, 0),
    )

    # Counted as a successful generation; the lost record only costs a
    # redundant idempotent pass next tick.
    assert totals["academy_count"] == 1
    assert totals["created"] == 5


# --- the catch-up window survives the month boundary ------------------------


@pytest.mark.asyncio
async def test_prior_period_is_caught_up_after_the_month_boundary() -> None:
    """A failure that persists past month end used to lose the month forever:
    ``period`` derives from the same ``now`` as the gate, so on the 1st the
    scheduler only ever looked at the new month."""
    db = _FakeDb()
    _seed_history(db, "academy-a", "2026-07")  # ran in July, lost August
    calls: list[str] = []

    async def _generate(period: str) -> _FakeResult:
        calls.append(period)
        return _FakeResult(created=6)

    totals = await _run_monthly_invoice_generation(
        db=db,
        academy_ids=["academy-a"],
        get_billing_settings=_settings_getter({"academy-a": _FakeSettings(1)}),
        generate=_generate,
        now=datetime(2026, 9, 1, 3, 0),
    )

    # Oldest first: August is repaired before September is generated.
    assert calls == ["2026-08", "2026-09"]
    assert totals["period_run_count"] == 2
    assert totals["catch_up_run_count"] == 1  # August only; September is on time
    assert db.generation_runs.periods_for("academy-a") == ["2026-07", "2026-08", "2026-09"]


@pytest.mark.asyncio
async def test_february_billing_day_28_still_gets_a_catch_up_attempt() -> None:
    """billing_day=28 in February leaves exactly one in-month tick. The prior
    period window is what gives that academy a second chance at all."""
    db = _FakeDb()
    _seed_history(db, "academy-a", "2026-01")
    calls: list[str] = []

    async def _generate(period: str) -> _FakeResult:
        calls.append(period)
        return _FakeResult(created=3)

    totals = await _run_monthly_invoice_generation(
        db=db,
        academy_ids=["academy-a"],
        get_billing_settings=_settings_getter({"academy-a": _FakeSettings(28)}),
        generate=_generate,
        # 1 March: February's only tick (the 28th) failed and left no record.
        now=datetime(2026, 3, 1, 3, 0),
    )

    assert calls == ["2026-02"]  # March is not due yet (billing_day 28)
    assert totals["catch_up_run_count"] == 1
    assert db.generation_runs.periods_for("academy-a") == ["2026-01", "2026-02"]


@pytest.mark.asyncio
async def test_prior_period_is_not_backfilled_without_generation_history() -> None:
    """Guard against retro-invoicing. On first deploy the collection is empty;
    attempting the prior period for every academy would invoice enrollments
    for a month they may not have been enrolled in — generation charges every
    currently-active enrollment for the requested period regardless of when it
    was created."""
    db = _FakeDb()
    calls: list[str] = []

    async def _generate(period: str) -> _FakeResult:
        calls.append(period)
        return _FakeResult(created=7)

    totals = await _run_monthly_invoice_generation(
        db=db,
        academy_ids=["academy-fresh"],
        get_billing_settings=_settings_getter({"academy-fresh": _FakeSettings(1)}),
        generate=_generate,
        now=datetime(2026, 9, 10, 3, 0),
    )

    assert calls == ["2026-09"]  # current period only, no August backfill
    assert totals["period_run_count"] == 1
    assert db.generation_runs.periods_for("academy-fresh") == ["2026-09"]


@pytest.mark.asyncio
async def test_prior_period_is_not_re_attempted_once_recorded() -> None:
    db = _FakeDb()
    _seed_history(db, "academy-a", "2026-08", "2026-09")
    calls: list[str] = []

    async def _generate(period: str) -> _FakeResult:
        calls.append(period)
        return _FakeResult(created=1)

    totals = await _run_monthly_invoice_generation(
        db=db,
        academy_ids=["academy-a"],
        get_billing_settings=_settings_getter({"academy-a": _FakeSettings(1)}),
        generate=_generate,
        now=datetime(2026, 9, 20, 3, 0),
    )

    assert calls == []
    assert totals["academy_count"] == 0


# ---------------------------------------------------------------------------
# Post-generation invoice emails (issue #430)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generated_invoices_are_emailed_per_academy_and_period() -> None:
    """Generation creating invoices is only half the job — nothing collected
    money until the send pass ran."""
    db = _FakeDb()
    _seed_history(db, "academy-a", "2026-08")
    _seed_history(db, "academy-b", "2026-08")
    sent: list[str] = []

    async def _generate(period: str) -> _FakeResult:
        return _FakeResult(created=2)

    async def _send(period: str) -> dict[str, int]:
        sent.append(period)
        return {"emailed": 2, "email_failed": 0, "skipped_autopay": 1}

    totals = await _run_monthly_invoice_generation(
        db=db,
        academy_ids=["academy-a", "academy-b"],
        get_billing_settings=_settings_getter(
            {"academy-a": _FakeSettings(1), "academy-b": _FakeSettings(1)}
        ),
        generate=_generate,
        now=datetime(2026, 9, 5, 3, 0),
        send_invoices=_send,
    )

    assert sent == ["2026-09", "2026-09"]  # once per academy
    assert totals["invoices_emailed"] == 4
    assert totals["invoice_emails_skipped_autopay"] == 2
    assert totals["invoice_emails_failed"] == 0


@pytest.mark.asyncio
async def test_the_send_pass_runs_on_ticks_that_generate_nothing() -> None:
    """The send pass is its own retry mechanism. `_due_periods` stops yielding
    a period the moment generation is recorded, so gating the emails on it
    would give every month exactly one delivery attempt — one Resend blip on
    billing day and nobody is ever told they owe money."""
    db = _FakeDb()
    _seed_history(db, "academy-a", "2026-08", "2026-09")
    generated: list[str] = []
    sent: list[str] = []

    async def _generate(period: str) -> _FakeResult:
        generated.append(period)
        return _FakeResult(created=1)

    async def _send(period: str) -> dict[str, int]:
        sent.append(period)
        return {"emailed": 1}

    totals = await _run_monthly_invoice_generation(
        db=db,
        academy_ids=["academy-a"],
        get_billing_settings=_settings_getter({"academy-a": _FakeSettings(1)}),
        generate=_generate,
        now=datetime(2026, 9, 20, 3, 0),
        send_invoices=_send,
    )

    assert generated == []  # nothing left to generate this month
    assert sent == ["2026-09"]  # but yesterday's undelivered invoices are retried
    assert totals["invoices_emailed"] == 1


@pytest.mark.asyncio
async def test_a_catch_up_period_is_emailed_on_the_tick_that_generates_it() -> None:
    db = _FakeDb()
    _seed_history(db, "academy-a", "2026-07")
    sent: list[str] = []

    async def _generate(period: str) -> _FakeResult:
        return _FakeResult(created=1)

    async def _send(period: str) -> dict[str, int]:
        sent.append(period)
        return {"emailed": 1}

    await _run_monthly_invoice_generation(
        db=db,
        academy_ids=["academy-a"],
        get_billing_settings=_settings_getter({"academy-a": _FakeSettings(1)}),
        generate=_generate,
        now=datetime(2026, 9, 5, 3, 0),
        send_invoices=_send,
    )

    # August (catch-up) and September, oldest first.
    assert sent == ["2026-08", "2026-09"]


@pytest.mark.asyncio
async def test_a_failing_send_pass_does_not_abort_the_remaining_academies() -> None:
    """An email provider outage must not cost the second academy its invoice
    generation record — that would re-walk every enrollment tomorrow."""
    db = _FakeDb()
    _seed_history(db, "academy-a", "2026-08")
    _seed_history(db, "academy-b", "2026-08")

    async def _generate(period: str) -> _FakeResult:
        return _FakeResult(created=1)

    async def _send(period: str) -> dict[str, int]:
        raise RuntimeError("resend is down")

    totals = await _run_monthly_invoice_generation(
        db=db,
        academy_ids=["academy-a", "academy-b"],
        get_billing_settings=_settings_getter(
            {"academy-a": _FakeSettings(1), "academy-b": _FakeSettings(1)}
        ),
        generate=_generate,
        now=datetime(2026, 9, 5, 3, 0),
        send_invoices=_send,
    )

    assert totals["academy_count"] == 2
    assert totals["created"] == 2
    assert totals["invoices_emailed"] == 0
    # Both academies still recorded generation, so tomorrow's tick will not
    # regenerate — only the undelivered invoices get retried.
    assert db.generation_runs.periods_for("academy-a") == ["2026-08", "2026-09"]
    assert db.generation_runs.periods_for("academy-b") == ["2026-08", "2026-09"]


@pytest.mark.asyncio
async def test_generation_without_a_send_pass_behaves_as_before() -> None:
    db = _FakeDb()
    _seed_history(db, "academy-a", "2026-08")

    async def _generate(period: str) -> _FakeResult:
        return _FakeResult(created=3)

    totals = await _run_monthly_invoice_generation(
        db=db,
        academy_ids=["academy-a"],
        get_billing_settings=_settings_getter({"academy-a": _FakeSettings(1)}),
        generate=_generate,
        now=datetime(2026, 9, 5, 3, 0),
    )

    assert totals["created"] == 3
    assert totals["invoices_emailed"] == 0
