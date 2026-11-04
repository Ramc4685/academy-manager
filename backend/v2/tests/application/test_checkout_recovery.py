"""Abandoned-checkout recovery (AI strategy Phase 1 #3): one email per
expired checkout or expired draft, only for the parent's latest application,
never twice."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.onboarding.application.use_cases.checkout_recovery import (
    RECOVERY_LOOKBACK,
    SendCheckoutRecoveryNotices,
)
from backend.v2.contexts.onboarding.domain.models import Application

pytestmark = pytest.mark.asyncio

ACADEMY_ID = "acad-1"
NOW = datetime(2026, 11, 4, 10, 10, tzinfo=UTC)


def _application(
    application_id: str,
    *,
    status: str,
    parent: str = "parent-1",
    updated_at: datetime | None = None,
    created_at: datetime | None = None,
) -> Application:
    created = created_at or NOW - timedelta(days=8)
    return Application(
        application_id=application_id,
        academy_id=ACADEMY_ID,
        parent_user_id=parent,
        parent_email="parent@example.com",
        status=status,  # type: ignore[arg-type]
        expires_at=created + timedelta(days=7),
        created_at=created,
        updated_at=updated_at or NOW - timedelta(hours=12),
    )


class FakeApplications:
    def __init__(self, applications: list[Application]) -> None:
        self._apps = applications

    async def list_by_status(self, statuses: list[str]) -> list[Application]:
        return sorted(
            (a for a in self._apps if a.status in statuses),
            key=lambda a: a.updated_at,
            reverse=True,
        )

    async def latest_for_parent(self, parent_user_id: str) -> Application | None:
        mine = [a for a in self._apps if a.parent_user_id == parent_user_id]
        return max(mine, key=lambda a: a.created_at) if mine else None


class FakeSendClaimRepository:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    async def try_claim(self, *, academy_id: str, subject_id: str, nudge_key: str):
        key = (academy_id, subject_id, nudge_key)
        for row in self.rows.values():
            if row["key"] == key:
                if row["status"] == "failed":
                    row["status"] = "queued"
                    return row
                return None
        row = {"send_id": f"send-{len(self.rows)}", "key": key, "status": "queued"}
        self.rows[row["send_id"]] = row
        return row

    async def mark_sent(self, academy_id: str, send_id: str) -> None:
        row = self.rows.get(send_id)
        if row is None or row["key"][0] != academy_id:
            return
        row["status"] = "sent"

    async def mark_failed(
        self, academy_id: str, send_id: str, reason: str, *, retryable: bool = True
    ) -> None:
        row = self.rows.get(send_id)
        if row is None or row["key"][0] != academy_id:
            return
        row["status"] = "failed" if retryable else "final"


class FakeNotifier:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def checkout_recovery(self, *, application: Application) -> str:
        self.sent.append(application.application_id)
        return "sent"


class FakeSwitch:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    async def is_enabled(self, academy_id: str) -> bool:
        return self.enabled


def _job(applications, *, send_repo=None, notifier=None, switch=None):
    return SendCheckoutRecoveryNotices(
        applications=FakeApplications(applications),
        send_repo=send_repo or FakeSendClaimRepository(),
        notifier=notifier or FakeNotifier(),
        switch=switch or FakeSwitch(),
    )


async def test_expired_checkouts_and_expired_drafts_get_one_notice_each() -> None:
    notifier = FakeNotifier()
    send_repo = FakeSendClaimRepository()
    job = _job(
        [
            _application("expired", status="CHECKOUT_EXPIRED", parent="p-1"),
            # Created 8 days ago: past the 7-day draft TTL, never checked out.
            _application("stale-draft", status="DRAFT", parent="p-2"),
            # A live draft (inside its TTL) is still being filled in.
            _application(
                "live-draft", status="DRAFT", parent="p-3", created_at=NOW - timedelta(days=2)
            ),
            _application("pending", status="PENDING_APPROVAL", parent="p-4"),
            _application("abandoned", status="ABANDONED", parent="p-5"),
        ],
        send_repo=send_repo,
        notifier=notifier,
    )

    assert await job.execute(academy_id=ACADEMY_ID, local_now=NOW) == 2
    assert sorted(notifier.sent) == ["expired", "stale-draft"]
    assert all(row["status"] == "sent" for row in send_repo.rows.values())

    # Second run: the claims are held, nothing goes out.
    assert await job.execute(academy_id=ACADEMY_ID, local_now=NOW) == 0
    assert len(notifier.sent) == 2


async def test_only_the_parents_latest_application_is_recovered() -> None:
    notifier = FakeNotifier()
    old = _application(
        "old",
        status="CHECKOUT_EXPIRED",
        parent="p-1",
        created_at=NOW - timedelta(days=10),
        updated_at=NOW - timedelta(hours=1),
    )
    fresh_draft = _application(
        "fresh", status="DRAFT", parent="p-1", created_at=NOW - timedelta(hours=1)
    )
    job = _job([old, fresh_draft], notifier=notifier)

    assert await job.execute(academy_id=ACADEMY_ID, local_now=NOW) == 0
    assert notifier.sent == []


async def test_applications_older_than_the_lookback_are_left_alone() -> None:
    notifier = FakeNotifier()
    stale = _application(
        "stale",
        status="CHECKOUT_EXPIRED",
        created_at=NOW - RECOVERY_LOOKBACK - timedelta(days=8),
        updated_at=NOW - RECOVERY_LOOKBACK - timedelta(days=1),
    )
    job = _job([stale], notifier=notifier)

    assert await job.execute(academy_id=ACADEMY_ID, local_now=NOW) == 0
    assert notifier.sent == []


async def test_switch_off_sends_and_claims_nothing() -> None:
    send_repo = FakeSendClaimRepository()
    job = _job(
        [_application("expired", status="CHECKOUT_EXPIRED")],
        send_repo=send_repo,
        switch=FakeSwitch(False),
    )

    assert await job.execute(academy_id=ACADEMY_ID, local_now=NOW) == 0
    assert send_repo.rows == {}
