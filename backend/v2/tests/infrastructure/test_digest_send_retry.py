"""Failed digest sends are retried on the next tick — and only failed ones (#435).

Before this, ``try_claim`` refused every second claim for a
``(academy, recipient, date)`` triple, including one whose row was ``failed``.
A transient Resend outage therefore cost that recipient the entire day's digest:
the claim was held forever by a row nothing would ever pick up again.

These tests run against the real repositories on mongomock (with the real unique
indexes installed) rather than the in-memory fakes used by the use-case tests,
because the behaviour under test *is* the conditional Mongo update.

The two invariants pull in opposite directions, so both are asserted throughout:
a failure must be retried, and a success must never be sent twice.
"""

from __future__ import annotations

import importlib
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from backend.v2.contexts.communications.application.ports import (
    AudienceResolver,
    ResolvedRecipient,
    SendOutcome,
)
from backend.v2.contexts.communications.application.use_cases.send_coach_daily_digest import (
    SendCoachDailyDigest,
    SendCoachDailyDigestCommand,
)
from backend.v2.contexts.communications.domain.models import (
    MAX_DIGEST_SEND_ATTEMPTS,
    AcademyAudience,
    DigestSendStatus,
)
from backend.v2.contexts.communications.infrastructure.mongo_digest_send_repo import (
    MongoDigestSendRepository,
)
from backend.v2.contexts.communications.infrastructure.mongo_parent_digest_send_repo import (
    MongoParentDigestSendRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope
from mongomock_motor import AsyncMongoMockClient

ACADEMY_ID = "acad-digest-retry"
DIGEST_DATE = "2026-06-12"

_coach_indexes = importlib.import_module("backend.v2.migrations.0125_coach_digest_send_indexes")
_parent_indexes = importlib.import_module("backend.v2.migrations.0148_parent_digest_send_indexes")
_backfill = importlib.import_module("backend.v2.migrations.0154_digest_send_attempt_count")


async def _coach_db() -> Any:
    db = AsyncMongoMockClient()["digest_retry_test"]
    await _coach_indexes.up(db)
    return db


# ---------------------------------------------------------------------------
# Repository-level: the claim rule itself
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_claim_is_reclaimed_on_the_next_tick() -> None:
    db = await _coach_db()
    with tenant_scope(ACADEMY_ID):
        repo = MongoDigestSendRepository(db)

        first = await repo.try_claim(ACADEMY_ID, "coach-1", DIGEST_DATE)
        assert first is not None
        assert first.attempt_count == 1
        await repo.mark_failed(first.digest_id, "resend timeout")

        retry = await repo.try_claim(ACADEMY_ID, "coach-1", DIGEST_DATE)
        assert retry is not None
        # Same row, re-queued — not a second claim row alongside the first.
        assert retry.digest_id == first.digest_id
        assert retry.status == DigestSendStatus.QUEUED
        assert retry.attempt_count == 2
        assert retry.failed_reason is None
        assert await db["coach_digest_sends"].count_documents({}) == 1


@pytest.mark.asyncio
async def test_sent_claim_is_never_reclaimed() -> None:
    """The whole point of the unique index: a delivered digest is never re-sent."""
    db = await _coach_db()
    with tenant_scope(ACADEMY_ID):
        repo = MongoDigestSendRepository(db)

        claim = await repo.try_claim(ACADEMY_ID, "coach-1", DIGEST_DATE)
        assert claim is not None
        await repo.mark_sent(claim.digest_id, "prov-1")

        assert await repo.try_claim(ACADEMY_ID, "coach-1", DIGEST_DATE) is None


@pytest.mark.asyncio
async def test_queued_and_skipped_claims_are_never_reclaimed() -> None:
    """An in-flight (queued) row must not be re-claimed by a concurrent tick,
    and a coach with nothing to teach is not re-examined all day."""
    db = await _coach_db()
    with tenant_scope(ACADEMY_ID):
        repo = MongoDigestSendRepository(db)

        queued = await repo.try_claim(ACADEMY_ID, "coach-queued", DIGEST_DATE)
        assert queued is not None
        assert await repo.try_claim(ACADEMY_ID, "coach-queued", DIGEST_DATE) is None

        skipped = await repo.try_claim(ACADEMY_ID, "coach-skip", DIGEST_DATE)
        assert skipped is not None
        await repo.mark_skipped_empty(skipped.digest_id)
        assert await repo.try_claim(ACADEMY_ID, "coach-skip", DIGEST_DATE) is None


@pytest.mark.asyncio
async def test_retries_stop_at_the_attempt_ceiling() -> None:
    db = await _coach_db()
    with tenant_scope(ACADEMY_ID):
        repo = MongoDigestSendRepository(db)

        claim = await repo.try_claim(ACADEMY_ID, "coach-1", DIGEST_DATE)
        assert claim is not None
        for expected_attempt in range(2, MAX_DIGEST_SEND_ATTEMPTS + 1):
            await repo.mark_failed(claim.digest_id, "still broken")
            claim = await repo.try_claim(ACADEMY_ID, "coach-1", DIGEST_DATE)
            assert claim is not None
            assert claim.attempt_count == expected_attempt

        # Attempts exhausted: the hourly tick stops burning sends on this row.
        assert claim.attempts_exhausted
        await repo.mark_failed(claim.digest_id, "still broken")
        assert await repo.try_claim(ACADEMY_ID, "coach-1", DIGEST_DATE) is None


@pytest.mark.asyncio
async def test_legacy_row_without_attempt_count_retries_after_backfill() -> None:
    """Rows written before #435 carry no ``attempt_count``; ``$lt`` would never
    match them, so the backfill migration is load-bearing, not cosmetic."""
    db = await _coach_db()
    with tenant_scope(ACADEMY_ID):
        repo = MongoDigestSendRepository(db)
        claim = await repo.try_claim(ACADEMY_ID, "coach-1", DIGEST_DATE)
        assert claim is not None
        await repo.mark_failed(claim.digest_id, "boom")
        # Simulate a row that predates the field.
        await db["coach_digest_sends"].update_one(
            {"digest_id": claim.digest_id}, {"$unset": {"attempt_count": ""}}
        )

        assert await repo.try_claim(ACADEMY_ID, "coach-1", DIGEST_DATE) is None

        await _backfill.up(db)
        retry = await repo.try_claim(ACADEMY_ID, "coach-1", DIGEST_DATE)
        assert retry is not None
        assert retry.attempt_count == 2


@pytest.mark.asyncio
async def test_parent_digest_failure_is_retried_and_success_is_not() -> None:
    db = AsyncMongoMockClient()["digest_retry_test"]
    await _parent_indexes.up(db)
    with tenant_scope(ACADEMY_ID):
        repo = MongoParentDigestSendRepository(db)

        failed = await repo.try_claim(ACADEMY_ID, "parent-1", DIGEST_DATE)
        assert failed is not None
        await repo.mark_failed(failed.digest_id, "smtp 421")
        retry = await repo.try_claim(ACADEMY_ID, "parent-1", DIGEST_DATE)
        assert retry is not None
        assert retry.digest_id == failed.digest_id
        assert retry.attempt_count == 2

        sent = await repo.try_claim(ACADEMY_ID, "parent-2", DIGEST_DATE)
        assert sent is not None
        await repo.mark_sent(sent.digest_id, "prov-2")
        assert await repo.try_claim(ACADEMY_ID, "parent-2", DIGEST_DATE) is None

        assert await db["parent_digest_sends"].count_documents({}) == 2


# ---------------------------------------------------------------------------
# Use-case level: the hourly tick actually recovers the lost digest
# ---------------------------------------------------------------------------


class _Resolver(AudienceResolver):
    def __init__(self, coaches: list[ResolvedRecipient]) -> None:
        self._coaches = coaches

    async def resolve_academy_audience(self, audience: AcademyAudience) -> list[ResolvedRecipient]:
        return list(self._coaches) if audience.role == "coach" else []

    async def resolve_session_audience(self, audience: Any) -> list[ResolvedRecipient]:
        return []

    async def resolve_coach_audience(self, audience: Any) -> list[ResolvedRecipient]:
        return []

    async def resolve_selected_audience(self, audience: Any) -> list[ResolvedRecipient]:
        return []

    async def resolve_payment_risk_audience(self, audience: Any) -> list[ResolvedRecipient]:
        return []


class _ScriptedSender:
    """Fails the first ``fail_first`` sends, then succeeds."""

    def __init__(self, fail_first: int) -> None:
        self._remaining_failures = fail_first
        self.sent: list[str] = []

    async def send(
        self,
        *,
        recipient: ResolvedRecipient,
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to: str | None = None,
    ) -> SendOutcome:
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            return SendOutcome(ok=False, provider_message_id=None, failed_reason="provider 503")
        self.sent.append(str(recipient.email))
        return SendOutcome(
            ok=True, provider_message_id=f"prov-{len(self.sent)}", failed_reason=None
        )


class _PlanProvider:
    async def execute(self, coach_id: str, on_date: date) -> Any:
        session = SimpleNamespace(
            title="Tuesday Juniors",
            location="Court A",
            start_at=None,
            end_at=None,
            groups=[
                SimpleNamespace(
                    level_name="Level 1",
                    youtube_links=[],
                    lesson_card=None,
                    students=[SimpleNamespace(student_name="Alice", focus=None, next_skill=None)],
                )
            ],
            unplaced=[],
        )
        return SimpleNamespace(
            date=on_date.isoformat(),
            program_name="Badminton",
            pathway_configured=True,
            sessions=[session],
        )


def _digest(db: Any, sender: _ScriptedSender) -> SendCoachDailyDigest:
    return SendCoachDailyDigest(
        digests=MongoDigestSendRepository(db),
        resolver=_Resolver([ResolvedRecipient("coach-1", "coach@example.test", "Coach One")]),
        sender=sender,  # type: ignore[arg-type]
        plan_provider=_PlanProvider(),
        now=lambda: datetime(2026, 6, 12, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_next_tick_recovers_a_failed_send_without_duplicating_it() -> None:
    db = await _coach_db()
    command = SendCoachDailyDigestCommand(academy_id=ACADEMY_ID, digest_date=date(2026, 6, 12))
    sender = _ScriptedSender(fail_first=1)

    with tenant_scope(ACADEMY_ID):
        first = await _digest(db, sender).execute(command)
        assert (first.sent, first.failed) == (0, 1)
        assert sender.sent == []

        # Next hourly tick: the failure is re-claimed and this time it lands.
        second = await _digest(db, sender).execute(command)
        assert (second.sent, second.failed) == (1, 0)
        assert sender.sent == ["coach@example.test"]

        # Third tick sends nothing — the row is now `sent`.
        third = await _digest(db, sender).execute(command)
        assert (third.sent, third.already_claimed) == (0, 1)
        assert sender.sent == ["coach@example.test"]
        assert await db["coach_digest_sends"].count_documents({}) == 1


@pytest.mark.asyncio
async def test_a_recipient_with_no_email_is_not_retried() -> None:
    """Retrying cannot conjure an address, and each retry re-runs plan
    generation. Marking it non-retryable also keeps it out of the ops digest's
    actionable count, so one un-onboarded coach cannot pin "attention needed"
    on every daily report forever."""
    db = await _coach_db()
    with tenant_scope(ACADEMY_ID):
        repo = MongoDigestSendRepository(db)
        claim = await repo.try_claim(ACADEMY_ID, "coach-1", DIGEST_DATE)
        assert claim is not None
        await repo.mark_failed(claim.digest_id, "no email address", retryable=False)

        assert await repo.try_claim(ACADEMY_ID, "coach-1", DIGEST_DATE) is None
        doc = await db["coach_digest_sends"].find_one({"digest_id": claim.digest_id})
        assert doc["retryable"] is False
        # Still visible to the admin delivery log with its reason.
        assert doc["failed_reason"] == "no email address"


@pytest.mark.asyncio
async def test_the_use_case_marks_a_missing_address_non_retryable() -> None:
    db = await _coach_db()
    command = SendCoachDailyDigestCommand(academy_id=ACADEMY_ID, digest_date=date(2026, 6, 12))
    sender = _ScriptedSender(fail_first=0)

    def _digest_no_email() -> SendCoachDailyDigest:
        return SendCoachDailyDigest(
            digests=MongoDigestSendRepository(db),
            resolver=_Resolver([ResolvedRecipient("coach-1", None, "Coach One")]),
            sender=sender,  # type: ignore[arg-type]
            plan_provider=_PlanProvider(),
            now=lambda: datetime(2026, 6, 12, tzinfo=UTC),
        )

    with tenant_scope(ACADEMY_ID):
        first = await _digest_no_email().execute(command)
        assert (first.sent, first.failed) == (0, 1)

        # The next tick must not re-run plan generation for an unreachable coach.
        second = await _digest_no_email().execute(command)
        assert (second.claimed, second.already_claimed) == (0, 1)
        assert sender.sent == []
