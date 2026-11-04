"""Owner daily brief is per academy (issue #776 follow-up).

The brief used to count every academy's rows together and mail the total to
one env-configured address. These tests run on a real ``mongod`` with every
migration applied (``real_db``), so the validators and unique indexes the
production collections carry are in force while two tenants are seeded side
by side.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.composition import owner_brief as owner_brief_module
from backend.v2.composition.owner_brief import send_owner_daily_briefs
from backend.v2.contexts.communications.application.ports import (
    ResolvedRecipient,
    SendOutcome,
)
from backend.v2.shared.observability.owner_daily_brief import (
    collect_owner_daily_brief,
    render_owner_daily_brief,
)

NOW = datetime(2026, 9, 28, 7, 30, tzinfo=UTC)
RECENT = NOW - timedelta(hours=2)
OLD = NOW - timedelta(days=5)

ACADEMY_A = "acad-brief-a"
ACADEMY_B = "acad-brief-b"
ACADEMY_C = "acad-brief-c"


async def _seed_academy(db: Any, academy_id: str, name: str) -> None:
    await db["academies"].insert_one(
        {"academy_id": academy_id, "display_name": name, "name": name, "status": "active"}
    )


async def _seed_signals(db: Any, academy_id: str, n: int) -> None:
    """``n`` of every counted signal for ``academy_id``, plus rows that must
    never count (outside the window / settled), all ids prefixed by tenant."""
    for i in range(n):
        await db["enrollments"].insert_one(
            {
                "academy_id": academy_id,
                "enrollment_id": f"{academy_id}-enr-{i}",
                "student_id": f"{academy_id}-stu-{i}",
                "session_id": f"{academy_id}-ses",
                "status": "active",
                "enrolled_at": RECENT,
            }
        )
        await db["enrollment_events"].insert_one(
            {
                "academy_id": academy_id,
                "event_id": f"{academy_id}-evt-{i}",
                "enrollment_id": f"{academy_id}-enr-{i}",
                "student_id": f"{academy_id}-stu-{i}",
                "event_type": "dropped",
                "reason": f"{academy_id} reason",
                "effective_at": RECENT,
                "occurred_at": RECENT,
            }
        )
        await db["onboarding_applications"].insert_one(
            {
                "academy_id": academy_id,
                "application_id": f"{academy_id}-app-{i}",
                "status": "PENDING_APPROVAL",
            }
        )
        await db["payments"].insert_one(
            {
                "academy_id": academy_id,
                "payment_id": f"{academy_id}-pay-{i}",
                "status": "failed",
                "amount_cents": 1000,
                "updated_at": RECENT,
            }
        )
        await db["invoices"].insert_one(
            {
                "academy_id": academy_id,
                "invoice_id": f"{academy_id}-inv-{i}",
                "status": "open",
                "balance_due_cents": 4500,
                "total_cents": 4500,
                "parent_id": f"{academy_id}-parent-{i}",
                "currency": "usd",
                "created_at": OLD,
                "updated_at": OLD,
            }
        )
        # Student i has a parent and no waiver.
        parent_id = f"{academy_id}-parent-{i}"
        await db["users"].insert_one(
            {
                "user_id": parent_id,
                "academy_id": academy_id,
                "email": f"{parent_id}@example.test",
                "role": "parent",
            }
        )
        await db["students"].insert_one(
            {
                "academy_id": academy_id,
                "student_id": f"{academy_id}-stu-{i}",
                "parent_id": parent_id,
                "first_name": "Kid",
                "last_name": str(i),
            }
        )
        await db["email_suppressions"].insert_one(
            {
                "suppression_id": f"{academy_id}-sup-{i}",
                "email": f"{parent_id}@example.test",
                "reason": "hard_bounce",
                "active": True,
                "first_seen_at": RECENT,
                "last_seen_at": RECENT,
            }
        )
    # A signed student: counted as a student, never as missing a waiver.
    await db["students"].insert_one(
        {
            "academy_id": academy_id,
            "student_id": f"{academy_id}-stu-signed",
            "parent_id": f"{academy_id}-parent-0",
            "first_name": "Signed",
            "last_name": "Kid",
        }
    )
    await db["waiver_acceptances"].insert_one(
        {
            "academy_id": academy_id,
            "acceptance_id": f"{academy_id}-wa",
            "student_id": f"{academy_id}-stu-signed",
            "accepted_at": OLD,
        }
    )
    # Never counted: old enrollment, settled invoice.
    await db["enrollments"].insert_one(
        {
            "academy_id": academy_id,
            "enrollment_id": f"{academy_id}-enr-old",
            "student_id": f"{academy_id}-stu-signed",
            "session_id": f"{academy_id}-ses-old",
            "status": "active",
            "enrolled_at": OLD,
        }
    )
    await db["invoices"].insert_one(
        {
            "academy_id": academy_id,
            "invoice_id": f"{academy_id}-inv-paid",
            "status": "paid",
            "balance_due_cents": 0,
            "total_cents": 4500,
            "parent_id": f"{academy_id}-parent-0",
            "currency": "usd",
            "created_at": OLD,
            "updated_at": OLD,
        }
    )


@pytest.mark.asyncio
async def test_each_academy_brief_counts_only_its_own_rows(real_db: Any) -> None:
    await _seed_academy(real_db, ACADEMY_A, "Alpha Academy")
    await _seed_academy(real_db, ACADEMY_B, "Bravo Academy")
    await _seed_signals(real_db, ACADEMY_A, 1)
    await _seed_signals(real_db, ACADEMY_B, 2)
    # A's opted-in family contact bounced too: still one of A's families.
    await real_db["family_contacts"].insert_one(
        {
            "academy_id": ACADEMY_A,
            "contact_id": "contact-a",
            "parent_id": f"{ACADEMY_A}-parent-0",
            "email": "Second.Parent@Example.test",
            "name": "Second Parent",
            "gets_notices": True,
            "created_at": OLD,
        }
    )
    await real_db["email_suppressions"].insert_one(
        {
            "suppression_id": "sup-contact-a",
            "email": "second.parent@example.test",
            "reason": "hard_bounce",
            "active": True,
            "first_seen_at": RECENT,
            "last_seen_at": RECENT,
        }
    )
    # Belongs to nobody in either academy: must never be counted.
    await real_db["email_suppressions"].insert_one(
        {
            "suppression_id": "sup-stranger",
            "email": "stranger@example.test",
            "reason": "hard_bounce",
            "active": True,
            "first_seen_at": RECENT,
            "last_seen_at": RECENT,
        }
    )

    brief_a = await collect_owner_daily_brief(real_db, academy_id=ACADEMY_A, now=NOW)
    brief_b = await collect_owner_daily_brief(real_db, academy_id=ACADEMY_B, now=NOW)

    assert brief_a.errors == []
    assert brief_b.errors == []
    assert brief_a.academy_name == "Alpha Academy"
    assert brief_b.academy_name == "Bravo Academy"

    assert brief_a.new_enrollments == 1
    assert brief_b.new_enrollments == 2
    assert [(r.reason, r.count) for r in brief_a.departures] == [(f"{ACADEMY_A} reason", 1)]
    assert [(r.reason, r.count) for r in brief_b.departures] == [(f"{ACADEMY_B} reason", 2)]
    assert brief_a.approvals_waiting == 1
    assert brief_b.approvals_waiting == 2
    assert brief_a.payments_failed == 1
    assert brief_b.payments_failed == 2
    assert brief_a.invoices_open == 1
    assert brief_b.invoices_open == 2
    assert brief_a.waivers_missing == 1
    assert brief_b.waivers_missing == 2
    assert brief_a.emails_undeliverable == 2  # parent + opted-in family contact
    assert brief_b.emails_undeliverable == 2


@pytest.mark.asyncio
async def test_brief_names_the_academy_in_subject_and_heading(real_db: Any) -> None:
    await _seed_academy(real_db, ACADEMY_A, "Alpha Academy")
    await _seed_signals(real_db, ACADEMY_A, 1)

    brief = await collect_owner_daily_brief(real_db, academy_id=ACADEMY_A, now=NOW)
    subject, body = render_owner_daily_brief(brief)

    # The prefix is what existing inbox filters match on; keep it first.
    assert subject.startswith("Academy brief 2026-09-28 — action needed")
    assert subject.endswith("· Alpha Academy")
    assert "Alpha Academy" in body


@pytest.mark.asyncio
async def test_legacy_waiver_acceptance_without_academy_id_still_counts(real_db: Any) -> None:
    # Pre-tenancy acceptances carry no academy_id; the admin waivers page
    # treats them as the student's own, and so must the brief.
    await _seed_academy(real_db, ACADEMY_A, "Alpha Academy")
    await real_db["students"].insert_one(
        {
            "academy_id": ACADEMY_A,
            "student_id": "legacy-stu",
            "parent_id": "legacy-parent",
            "first_name": "L",
            "last_name": "S",
        }
    )
    await real_db["waiver_acceptances"].insert_one(
        {"acceptance_id": "legacy-wa", "student_id": "legacy-stu", "accepted_at": OLD}
    )

    brief = await collect_owner_daily_brief(real_db, academy_id=ACADEMY_A, now=NOW)

    assert brief.waivers_missing == 0


# ---------------------------------------------------------------------------
# Orchestration: who gets which academy's brief.
# ---------------------------------------------------------------------------


class _RecordingSender:
    """Records every send; ``fail_for`` raises for one address, the way a
    provider adapter bug would, so the loop's isolation is exercised."""

    def __init__(self, fail_for: str | None = None) -> None:
        self.sent: list[tuple[ResolvedRecipient, str, str]] = []
        self.fail_for = fail_for

    async def send(
        self, *, recipient: ResolvedRecipient, subject: str, body: str, **_: Any
    ) -> SendOutcome:
        if self.fail_for and recipient.email == self.fail_for:
            raise RuntimeError("provider exploded")
        self.sent.append((recipient, subject, body))
        return SendOutcome(ok=True, provider_message_id="msg", failed_reason=None)


async def _seed_owner(
    db: Any,
    academy_id: str,
    user_id: str,
    email: str,
    *,
    status: str = "active",
    role: str = "owner",
) -> None:
    await db["users"].insert_one(
        {"user_id": user_id, "academy_id": academy_id, "email": email, "display_name": user_id}
    )
    await db["academy_memberships"].insert_one(
        {
            "membership_id": f"m-{academy_id}-{user_id}",
            "academy_id": academy_id,
            "user_id": user_id,
            "role": role,
            "roles": [role],
            "status": status,
        }
    )


async def _seed_two_tenants(db: Any) -> None:
    await _seed_academy(db, ACADEMY_A, "Alpha Academy")
    await _seed_academy(db, ACADEMY_B, "Bravo Academy")
    await _seed_owner(db, ACADEMY_A, "owner-a", "owner-a@example.test")
    await _seed_owner(db, ACADEMY_B, "owner-b", "owner-b@example.test")
    await _seed_owner(db, ACADEMY_B, "owner-b2", "owner-b2@example.test")
    # Not recipients: B's revoked owner and B's coach.
    await _seed_owner(db, ACADEMY_B, "ex-owner-b", "ex-owner-b@example.test", status="revoked")
    await _seed_owner(db, ACADEMY_B, "coach-b", "coach-b@example.test", role="coach")


def _by_email(sender: _RecordingSender) -> dict[str, tuple[ResolvedRecipient, str, str]]:
    return {rec.email or "": (rec, subject, body) for rec, subject, body in sender.sent}


@pytest.mark.asyncio
async def test_house_academy_keeps_env_recipient_and_others_go_to_their_owners(
    real_db: Any,
) -> None:
    await _seed_two_tenants(real_db)
    sender = _RecordingSender()

    summary = await send_owner_daily_briefs(
        real_db,
        sender=sender,
        academy_ids=[ACADEMY_A, ACADEMY_B],
        house_academy_id=ACADEMY_A,
        override_email="ops@blno.test",
        now=NOW,
    )

    sent = _by_email(sender)
    assert set(sent) == {"ops@blno.test", "owner-b@example.test", "owner-b2@example.test"}
    # BLNO regression: exactly one email to the env address, same identity.
    to_env = [rec for rec, _, _ in sender.sent if rec.email == "ops@blno.test"]
    assert len(to_env) == 1
    assert to_env[0].user_id == "owner-brief"
    assert to_env[0].display_name == "Owner"
    assert sent["ops@blno.test"][1].endswith("· Alpha Academy")
    # B's brief never reaches the env address or A's owner.
    for email in ("owner-b@example.test", "owner-b2@example.test"):
        assert sent[email][1].endswith("· Bravo Academy")
    assert "owner-a@example.test" not in sent
    assert summary.sent == 3
    assert summary.failed == 0


@pytest.mark.asyncio
async def test_house_academy_without_env_address_goes_to_its_owners(real_db: Any) -> None:
    await _seed_two_tenants(real_db)
    sender = _RecordingSender()

    await send_owner_daily_briefs(
        real_db,
        sender=sender,
        academy_ids=[ACADEMY_A, ACADEMY_B],
        house_academy_id=ACADEMY_A,
        override_email=None,
        now=NOW,
    )

    sent = _by_email(sender)
    assert set(sent) == {"owner-a@example.test", "owner-b@example.test", "owner-b2@example.test"}
    assert sent["owner-a@example.test"][0].user_id == "owner-a"
    assert sent["owner-a@example.test"][1].endswith("· Alpha Academy")


@pytest.mark.asyncio
async def test_env_address_never_receives_a_non_house_academy_brief(real_db: Any) -> None:
    await _seed_two_tenants(real_db)
    sender = _RecordingSender()

    # The house academy is somebody else entirely: neither A nor B may use
    # the env address.
    await send_owner_daily_briefs(
        real_db,
        sender=sender,
        academy_ids=[ACADEMY_A, ACADEMY_B],
        house_academy_id="the-house",
        override_email="ops@blno.test",
        now=NOW,
    )

    assert "ops@blno.test" not in _by_email(sender)


@pytest.mark.asyncio
async def test_one_academy_failing_does_not_stop_the_others(
    real_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_two_tenants(real_db)
    await _seed_academy(real_db, ACADEMY_C, "Charlie Academy")
    await _seed_owner(real_db, ACADEMY_C, "owner-c", "owner-c@example.test")
    captured: list[str] = []
    monkeypatch.setattr(owner_brief_module, "capture_message", captured.append)
    sender = _RecordingSender(fail_for="owner-a@example.test")

    summary = await send_owner_daily_briefs(
        real_db,
        sender=sender,
        academy_ids=[ACADEMY_A, ACADEMY_B, ACADEMY_C],
        house_academy_id=ACADEMY_A,
        override_email=None,
        now=NOW,
    )

    sent = _by_email(sender)
    assert set(sent) == {"owner-b@example.test", "owner-b2@example.test", "owner-c@example.test"}
    assert summary.failed == 1
    assert len(captured) == 1
    assert ACADEMY_A in captured[0]


@pytest.mark.asyncio
async def test_academy_without_an_owner_is_skipped(real_db: Any) -> None:
    await _seed_two_tenants(real_db)
    await _seed_academy(real_db, ACADEMY_C, "Charlie Academy")
    sender = _RecordingSender()

    summary = await send_owner_daily_briefs(
        real_db,
        sender=sender,
        academy_ids=[ACADEMY_B, ACADEMY_C],
        house_academy_id=ACADEMY_A,
        override_email="ops@blno.test",
        now=NOW,
    )

    assert sender.sent
    assert all(subject.endswith("· Bravo Academy") for _, subject, _ in sender.sent)
    assert summary.skipped_no_recipient == 1
