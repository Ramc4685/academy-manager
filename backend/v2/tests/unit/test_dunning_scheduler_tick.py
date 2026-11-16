"""The hourly dunning tick across academies (L1: findings A4-9, A7-1)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.v2.main import _run_dunning_for_academies
from backend.v2.shared.tenancy.context import current_academy_id


class _Worker:
    def __init__(self, *, fail_for: set[str] | None = None) -> None:
        self.fail_for = fail_for or set()
        self.called: list[str] = []

    async def execute(self, *, limit: int, worker_id: str):
        academy_id = current_academy_id()
        self.called.append(academy_id)
        if academy_id in self.fail_for:
            raise ValueError("dunning state changed during park; retry")
        return SimpleNamespace(processed=2, parked=1, technical_failures=1, succeeded=1)


@pytest.mark.asyncio
async def test_one_academys_dunning_failure_does_not_abort_the_rest() -> None:
    worker = _Worker(fail_for={"academy-bad"})

    totals = await _run_dunning_for_academies(
        academy_ids=["academy-bad", "academy-good"],
        late_fees=None,
        worker=worker,
    )

    assert worker.called == ["academy-bad", "academy-good"]
    assert totals["academy_count"] == 1
    assert totals["academy_failures"] == 1
    assert totals["processed"] == 2


@pytest.mark.asyncio
async def test_parked_and_technical_failures_are_carried_into_totals() -> None:
    totals = await _run_dunning_for_academies(
        academy_ids=["a", "b"], late_fees=None, worker=_Worker()
    )

    assert totals["parked"] == 2
    assert totals["technical_failures"] == 2


# --- A7-5 / G:jobs_data_infra:7: every money loop isolates academies ---------


@pytest.mark.asyncio
async def test_dunning_failure_is_logged_once_at_error(caplog) -> None:
    """Sentry gets ERROR logs through LoggingIntegration; an extra
    capture_exception would report every failure twice."""
    import logging

    with caplog.at_level(logging.ERROR):
        await _run_dunning_for_academies(
            academy_ids=["academy-bad"], late_fees=None, worker=_Worker(fail_for={"academy-bad"})
        )

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert [r.getMessage() for r in errors] == ["dunning_academy_failed"]
    assert errors[0].exc_info is not None


@pytest.mark.asyncio
async def test_isolated_loop_runs_every_academy_then_fails_the_job(caplog) -> None:
    import logging

    import backend.v2.main as main_module

    ran: list[str] = []

    async def _run(academy_id: str) -> None:
        ran.append(academy_id)
        if academy_id == "academy-bad":
            raise RuntimeError("stripe connection revoked")

    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError, match="1 academy"):
        await main_module._run_isolated_per_academy(
            "process_stripe_webhook_events", ["academy-bad", "academy-good"], _run
        )

    assert ran == ["academy-bad", "academy-good"]
    assert any("scheduled_job_academy_failed" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_isolated_loop_is_quiet_when_every_academy_succeeds() -> None:
    import backend.v2.main as main_module

    async def _run(academy_id: str) -> None:
        return None

    await main_module._run_isolated_per_academy("job", ["a", "b"], _run)


@pytest.mark.parametrize(
    "body", ["_process_stripe_webhook_events_body", "_reconcile_stripe_payment_intents_body"]
)
def test_stripe_loops_run_each_academy_isolated(body: str) -> None:
    import inspect

    from backend.v2.main import _lifespan

    source = inspect.getsource(_lifespan).split(f"async def {body}", 1)[1]
    source = source.split("\n    async def ", 1)[0]
    assert "await _run_isolated_per_academy(" in source
    assert "for academy_id in" not in source
