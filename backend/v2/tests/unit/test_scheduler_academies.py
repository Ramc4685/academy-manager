from __future__ import annotations

import inspect
from datetime import datetime

import pytest

from backend.v2.main import (
    _lifespan,
    _run_monthly_invoice_generation,
    _scheduler_academy_ids,
)


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
    gate = inspect.getsource(_run_monthly_invoice_generation)
    assert "if now.day < billing_day:" in gate
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
        existing = await self.find_one(query)
        if existing is None:
            assert upsert
            existing = dict(update.get("$setOnInsert") or {})
            self.docs.append(existing)
        existing.update(update.get("$set") or {})


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
    def __init__(self, created: int = 0, skipped_existing: int = 0) -> None:
        self.created = created
        self.skipped_existing = skipped_existing


def _settings_getter(by_academy: dict[str, object]):
    from backend.v2.shared.tenancy import current_academy_id

    async def _get() -> object:
        value = by_academy[current_academy_id()]
        if isinstance(value, Exception):
            raise value
        return value

    return _get


@pytest.mark.asyncio
async def test_catch_up_generates_when_billing_day_already_passed() -> None:
    """The 03:00 run on billing_day failed (nothing recorded). Two days later
    the daily tick must still invoice the month instead of skipping it."""
    db = _FakeDb()
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
    assert totals["catch_up_academy_count"] == 1
    # The successful run is recorded so later ticks stop retrying.
    assert db.generation_runs.docs[0]["academy_id"] == "academy-a"
    assert db.generation_runs.docs[0]["period"] == "2026-09"


@pytest.mark.asyncio
async def test_no_regeneration_the_day_after_a_successful_run() -> None:
    """Without the run record the catch-up window would re-walk every academy
    every day for the rest of the month."""
    db = _FakeDb()
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
    assert len(db.generation_runs.docs) == 1


@pytest.mark.asyncio
async def test_before_billing_day_nothing_is_generated() -> None:
    db = _FakeDb()
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
    assert db.generation_runs.docs == []


@pytest.mark.asyncio
async def test_one_academys_bad_billing_settings_does_not_abort_the_rest() -> None:
    """The settings read moved inside the per-academy try (issue #431): a
    single unreadable billing_settings document used to abort the whole run,
    silently skipping every academy after it."""
    db = _FakeDb()
    generated: list[str] = []

    async def _generate(period: str) -> _FakeResult:
        from backend.v2.shared.tenancy import current_academy_id

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

    assert generated == ["academy-good"]
    assert totals["academy_count"] == 1
    assert totals["created"] == 2
    # The failed academy leaves no record, so the next tick retries it.
    assert [doc["academy_id"] for doc in db.generation_runs.docs] == ["academy-good"]


@pytest.mark.asyncio
async def test_generation_failure_leaves_no_record_so_the_next_tick_retries() -> None:
    db = _FakeDb()
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
    assert db.generation_runs.docs == []

    second = await _run_monthly_invoice_generation(
        db=db,
        academy_ids=["academy-a"],
        get_billing_settings=settings,
        generate=_flaky,
        now=datetime(2026, 9, 2, 3, 0),
    )

    assert attempts == ["2026-09", "2026-09"]
    assert second["created"] == 3
    assert second["catch_up_academy_count"] == 1
    assert len(db.generation_runs.docs) == 1
