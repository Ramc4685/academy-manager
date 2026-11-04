"""``CancelAccountDeletion``: support-only restore of a self-deleted account (PR #1115)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.identity.application.use_cases.cancel_account_deletion import (
    CancelAccountDeletion,
)
from backend.v2.contexts.identity.domain.account_deletion import AccountDeletionRequest
from backend.v2.contexts.identity.domain.errors import (
    AccountDeletionInProgress,
    AccountDeletionRequestNotFound,
)

NOW = datetime(2026, 11, 10, 12, tzinfo=UTC)

REQUEST = AccountDeletionRequest(
    request_id="r1",
    user_id="u1",
    auth_uid="fb1",
    email="p@example.com",
    aliases=("u1", "fb1"),
    academy_ids=("acad-a", "acad-b"),
    requested_at=NOW - timedelta(days=2),
    execute_after=NOW + timedelta(days=12),
)


class Store:
    """Mirrors MongoAccountDeletionStore: cancel only takes an unclaimed,
    never-attempted scheduled row, and restore only reverses rows the
    deletion removed (those carrying ``status_before_deletion``)."""

    def __init__(self, row: dict[str, Any] | None) -> None:
        self.rows = {row["request"].request_id: row} if row else {}
        self.memberships = [
            {"academy_id": "acad-a", "user_id": "u1", "status": "removed", "before": "active"},
            {"academy_id": "acad-b", "user_id": "fb1", "status": "removed", "before": "suspended"},
            {"academy_id": "acad-c", "user_id": "u1", "status": "removed", "before": None},
        ]

    async def cancel_request(self, request_id: str) -> AccountDeletionRequest | None:
        row = self.rows.get(request_id)
        if (
            row is None
            or row["request"].status != "scheduled"
            or row.get("claimed_at")
            or row.get("attempts", 0) > 0
        ):
            return None
        return self.rows.pop(request_id)["request"]  # type: ignore[no-any-return]

    async def request_exists(self, request_id: str) -> bool:
        return request_id in self.rows

    async def restore_memberships(self, *, aliases: tuple[str, ...], now: datetime) -> None:
        for m in self.memberships:
            if m["user_id"] in aliases and m["status"] == "removed" and m["before"]:
                m["status"], m["before"] = m["before"], None


class Firebase:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[str, bool]] = []
        self._fail = fail

    async def set_user_disabled(self, uid: str, disabled: bool) -> None:
        if self._fail:
            raise RuntimeError("firebase down")
        self.calls.append((uid, disabled))


def _statuses(store: Store) -> dict[str, str]:
    return {m["academy_id"]: m["status"] for m in store.memberships}


@pytest.mark.asyncio
async def test_cancel_restores_every_academy_and_re_enables_the_login() -> None:
    store, firebase = Store({"request": REQUEST}), Firebase()

    result = await CancelAccountDeletion(store=store, firebase=firebase).execute("r1", now=NOW)

    assert result.firebase_enabled and result.request.academy_ids == ("acad-a", "acad-b")
    assert store.rows == {}
    assert _statuses(store) == {"acad-a": "active", "acad-b": "suspended", "acad-c": "removed"}
    assert firebase.calls == [("fb1", False)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "row",
    [
        {"request": replace(REQUEST, status="running"), "claimed_at": NOW},
        {"request": REQUEST, "claimed_at": NOW - timedelta(hours=3), "attempts": 1},
        {"request": REQUEST, "attempts": 1},
    ],
    ids=["claimed", "failed-after-claim", "attempted"],
)
async def test_cancel_is_refused_once_the_erasure_claimed_or_attempted_it(row) -> None:
    store, firebase = Store(row), Firebase()

    with pytest.raises(AccountDeletionInProgress):
        await CancelAccountDeletion(store=store, firebase=firebase).execute("r1", now=NOW)

    assert "r1" in store.rows
    assert set(_statuses(store).values()) == {"removed"}
    assert firebase.calls == []


@pytest.mark.asyncio
async def test_an_unknown_request_is_not_found() -> None:
    with pytest.raises(AccountDeletionRequestNotFound):
        await CancelAccountDeletion(store=Store(None), firebase=Firebase()).execute("nope")


@pytest.mark.asyncio
async def test_a_firebase_outage_is_reported_not_raised() -> None:
    store = Store({"request": REQUEST})

    result = await CancelAccountDeletion(store=store, firebase=Firebase(fail=True)).execute("r1")

    assert not result.firebase_enabled
    assert _statuses(store)["acad-a"] == "active"
