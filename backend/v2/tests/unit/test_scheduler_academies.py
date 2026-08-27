from __future__ import annotations

import inspect

import pytest

from backend.v2.main import _lifespan, _scheduler_academy_ids


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
    assert "billing_settings.billing_day != now.day" in source


def test_monthly_invoice_job_holds_a_distributed_lease() -> None:
    """Two Fly machines running generation concurrently would race on the same
    invoices; the lease is what keeps exactly one machine generating."""
    source = inspect.getsource(_lifespan)

    assert 'job_lease(\n            db, "generate_monthly_invoices"' in source
