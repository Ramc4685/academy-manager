"""The composed account-deletion executor on a real ``mongod`` (mobile M5, D3).

Real validators and indexes (``users.normalized_email`` is unique and sparse,
``students`` requires ``parent_id``). Dropping classes is a recording fake: its
own billing behaviour is covered by the enrollment tests; here it only has to
be called once per child. Stripe and Firebase are fakes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.composition.account_deletion import compose_execute_account_deletions
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.contexts.enrollment.application.use_cases.stop_all_classes import (
    StopAllClassesResult,
)

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 11, 20, 12, tzinfo=UTC)
A = "acad-a"


class RecordingStopAll:
    def __init__(self) -> None:
        self.students: list[str] = []

    async def execute(self, cmd: Any) -> StopAllClassesResult:
        assert cmd.outcome == "adjustment"
        self.students.append(cmd.student_id)
        return StopAllClassesResult(student_id=cmd.student_id, results=[])


class FakeFirebase:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete_user(self, uid: str) -> None:
        self.deleted.append(uid)


async def _seed(db: Any, *, guardian_active: bool = False) -> None:
    await db["account_deletion_requests"].insert_one(
        {
            "request_id": "r1",
            "user_id": "u1",
            "auth_uid": "fb1",
            "email": "p@example.com",
            "aliases": ["u1", "fb1"],
            "academy_ids": [A],
            "requested_at": NOW - timedelta(days=15),
            "execute_after": NOW - timedelta(hours=1),
            "status": "scheduled",
        }
    )
    await db["users"].insert_one(
        {
            "user_id": "u1",
            "firebase_uid": "fb1",
            "email": "p@example.com",
            "normalized_email": "p@example.com",
            "display_name": "Pat Parent",
            "phone": "+15555550100",
        }
    )
    await db["students"].insert_many(
        [
            {
                "academy_id": A,
                "student_id": "stu-abcd",
                "parent_id": "u1",
                "full_name": "Kid One",
                "date_of_birth": "2015-04-01",
                "medical_notes": "asthma",
            },
            {"academy_id": A, "student_id": "stu-other", "parent_id": "u9", "full_name": "Other"},
        ]
    )
    await db["family_contacts"].insert_one(
        {"academy_id": A, "parent_id": "u1", "contact_id": "c1", "email": "g@example.com"}
    )
    await db["family_notes"].insert_one({"academy_id": A, "parent_id": "u1", "body": "note"})
    await db["crm_contacts"].insert_one(
        {"academy_id": A, "contact_id": "lead1", "converted_parent_id": "u1", "name": "Pat"}
    )
    await db["messages"].insert_one({"academy_id": A, "message_id": "m1", "sender_id": "fb1"})
    await db["message_deliveries"].insert_one(
        {"academy_id": A, "recipient_user_id": "u1", "recipient_email": "p@example.com"}
    )
    await db["email_preferences"].insert_one({"academy_id": A, "user_id": "u1"})
    await db["parent_billing_customers"].insert_one(
        {
            "academy_id": A,
            "parent_id": "u1",
            "stripe_customer_id": "cus_1",
            "default_payment_method_id": "pm_1",
            "payment_method_last4": "4242",
            "created_at": NOW,
        }
    )
    if guardian_active:
        await db["users"].insert_one(
            {"user_id": "g1", "email": "g@example.com", "normalized_email": "g@example.com"}
        )
        await db["academy_memberships"].insert_one(
            {
                "membership_id": "mg",
                "academy_id": A,
                "user_id": "g1",
                "roles": ["parent"],
                "status": "active",
            }
        )


def _job(db: Any) -> tuple[Any, RecordingStopAll, FakeStripeGateway, FakeFirebase]:
    stop_all, stripe, firebase = RecordingStopAll(), FakeStripeGateway(), FakeFirebase()
    stripe.attached_payment_methods[(None, "cus_1")] = ["pm_1"]
    job = compose_execute_account_deletions(
        db,
        stop_all_classes=stop_all,  # type: ignore[arg-type]
        stripe=stripe,
        firebase=firebase,
    )
    return job, stop_all, stripe, firebase


async def test_erases_the_account_and_keeps_what_the_academy_must_keep(real_db: Any) -> None:
    await _seed(real_db)
    job, stop_all, stripe, firebase = _job(real_db)

    result = await job.execute(now=NOW)

    assert (result.completed, result.failed) == (1, 0)
    assert stop_all.students == ["stu-abcd"]
    user = await real_db["users"].find_one({"user_id": "u1"})
    assert user["display_name"] == "Deleted user" and user["status"] == "deleted"
    assert "normalized_email" not in user and user["phone"] is None
    assert "p@example.com" not in str(user)
    kid = await real_db["students"].find_one({"student_id": "stu-abcd"})
    assert kid["full_name"] == "Student ABCD"
    assert "date_of_birth" not in kid and "medical_notes" not in kid
    other = await real_db["students"].find_one({"student_id": "stu-other"})
    assert other["full_name"] == "Other"
    for name in ("family_contacts", "family_notes", "crm_contacts", "email_preferences"):
        assert await real_db[name].count_documents({}) == 0, name
    message = await real_db["messages"].find_one({"message_id": "m1"})
    assert message["author_display_name"] == "Deleted user"
    delivery = await real_db["message_deliveries"].find_one({})
    assert "recipient_email" not in delivery
    customer = await real_db["parent_billing_customers"].find_one({"parent_id": "u1"})
    assert customer["stripe_customer_id"] == "cus_1"
    assert "default_payment_method_id" not in customer and "payment_method_last4" not in customer
    assert stripe.attached_payment_methods == {}
    assert firebase.deleted == ["fb1"]
    request = await real_db["account_deletion_requests"].find_one({"request_id": "r1"})
    assert request["status"] == "completed" and "email" not in request
    assert await real_db["audit_logs"].count_documents({"action": "user.deletion_completed"}) == 1

    # Nothing is due any more; a second tick is a no-op.
    again = await job.execute(now=NOW)
    assert (again.completed, again.failed) == (0, 0)


async def test_children_stay_when_another_guardian_still_signs_in(real_db: Any) -> None:
    await _seed(real_db, guardian_active=True)
    job, stop_all, _stripe, _firebase = _job(real_db)

    assert (await job.execute(now=NOW)).completed == 1

    assert stop_all.students == ["stu-abcd"]  # classes still dropped: billing was the parent's
    kid = await real_db["students"].find_one({"student_id": "stu-abcd"})
    assert kid["full_name"] == "Kid One"
    assert await real_db["family_contacts"].count_documents({}) == 1
    user = await real_db["users"].find_one({"user_id": "u1"})
    assert user["display_name"] == "Deleted user"


async def test_not_yet_due_requests_are_left_alone(real_db: Any) -> None:
    await _seed(real_db)
    await real_db["account_deletion_requests"].update_one(
        {"request_id": "r1"}, {"$set": {"execute_after": NOW + timedelta(days=1)}}
    )
    job, stop_all, _stripe, firebase = _job(real_db)

    assert (await job.execute(now=NOW)).completed == 0
    assert stop_all.students == [] and firebase.deleted == []
    assert (await real_db["users"].find_one({"user_id": "u1"}))["display_name"] == "Pat Parent"


async def test_a_failing_request_backs_off_instead_of_blocking_the_queue(real_db: Any) -> None:
    await _seed(real_db)
    stop_all, stripe = RecordingStopAll(), FakeStripeGateway()

    class DownFirebase:
        async def delete_user(self, uid: str) -> None:
            raise RuntimeError("firebase down")

    job = compose_execute_account_deletions(
        real_db,
        stop_all_classes=stop_all,
        stripe=stripe,
        firebase=DownFirebase(),  # type: ignore[arg-type]
    )
    assert (await job.execute(now=NOW)).failed == 1
    row = await real_db["account_deletion_requests"].find_one({"request_id": "r1"})
    assert row["status"] == "scheduled" and row["attempts"] == 1
    assert row["last_error"]["step"] == "firebase"
    assert row["execute_after"].replace(tzinfo=UTC) == NOW + timedelta(hours=1)
    # Not picked up again until the back-off passes.
    assert (await job.execute(now=NOW + timedelta(minutes=30))).failed == 0


async def test_back_off_is_capped_at_a_day_however_many_attempts(real_db: Any) -> None:
    from backend.v2.contexts.identity.infrastructure.mongo_account_deletion_store import (
        MongoAccountDeletionStore,
    )

    await _seed(real_db)
    await real_db["account_deletion_requests"].update_one(
        {"request_id": "r1"}, {"$set": {"attempts": 500}}
    )
    await MongoAccountDeletionStore(real_db).record_failure("r1", step="x", error="e", now=NOW)
    row = await real_db["account_deletion_requests"].find_one({"request_id": "r1"})
    assert row["attempts"] == 501
    assert row["execute_after"].replace(tzinfo=UTC) == NOW + timedelta(days=1)
