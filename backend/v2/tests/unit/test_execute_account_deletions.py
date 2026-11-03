"""``ExecuteAccountDeletions`` orchestration (mobile M5, D3): order, retry, isolation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.identity.application.use_cases.execute_account_deletions import (
    ExecuteAccountDeletions,
)
from backend.v2.contexts.identity.domain.account_deletion import AccountDeletionRequest

NOW = datetime(2026, 11, 20, 12, tzinfo=UTC)


def _request(n: int) -> AccountDeletionRequest:
    return AccountDeletionRequest(
        request_id=f"r{n}",
        user_id=f"u{n}",
        auth_uid=f"fb{n}",
        email=f"p{n}@example.com",
        aliases=(f"u{n}", f"fb{n}"),
        academy_ids=("acad-a",),
        requested_at=NOW - timedelta(days=15),
        execute_after=NOW - timedelta(days=1),
    )


class Store:
    def __init__(self, *requests: AccountDeletionRequest) -> None:
        self.requests = list(requests)
        self.calls: list[str] = []
        self.failures: list[tuple[str, str]] = []

    async def due_requests(self, *, now, limit):
        return list(self.requests)

    async def anonymise_identity(self, request, *, now):
        self.calls.append(f"identity:{request.request_id}")

    async def mark_completed(self, request_id, *, now):
        self.calls.append(f"completed:{request_id}")

    async def record_failure(self, request_id, *, step, error, now):
        self.failures.append((request_id, step))


class Step:
    def __init__(self, name: str, calls: list[str], *, fail_for: str = "") -> None:
        self.name = name
        self._calls = calls
        self._fail_for = fail_for

    async def erase(self, request, *, now):
        if request.request_id == self._fail_for:
            raise RuntimeError("boom")
        self._calls.append(f"{self.name}:{request.request_id}")


class Firebase:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    async def delete_user(self, uid):
        self._calls.append(f"firebase:{uid}")


@pytest.mark.asyncio
async def test_runs_every_step_then_identity_then_firebase_last() -> None:
    store = Store(_request(1))
    job = ExecuteAccountDeletions(
        store=store,
        steps=[Step("family", store.calls), Step("billing", store.calls)],
        firebase=Firebase(store.calls),
    )
    result = await job.execute(now=NOW)
    assert (result.completed, result.failed) == (1, 0)
    assert store.calls == [
        "family:r1",
        "billing:r1",
        "identity:r1",
        "firebase:fb1",
        "completed:r1",
    ]


@pytest.mark.asyncio
async def test_a_failing_account_is_recorded_and_does_not_stop_the_others() -> None:
    store = Store(_request(1), _request(2))
    job = ExecuteAccountDeletions(
        store=store,
        steps=[Step("family", store.calls), Step("billing", store.calls, fail_for="r1")],
        firebase=Firebase(store.calls),
    )
    result = await job.execute(now=NOW)
    assert (result.completed, result.failed) == (1, 1)
    assert store.failures == [("r1", "billing")]
    # r1 never reached identity, Firebase or completion: the next tick retries it.
    assert [c for c in store.calls if c.endswith("r1") or c.endswith("fb1")] == ["family:r1"]
    assert "completed:r2" in store.calls
