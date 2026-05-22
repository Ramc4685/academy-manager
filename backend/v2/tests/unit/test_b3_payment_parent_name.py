from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import (
    MongoPaymentRepository,
)


def _make_payment_doc(**kwargs):
    base = {
        "payment_id": "p1",
        "parent_id": "firebase-uid-abc",
        "student_id": "s1",
        "amount_cents": 5000,
        "status": "succeeded",
        "period": "2026-05",
        "created_at": datetime.now(UTC),
    }
    return {**base, **kwargs}


def test_to_admin_row_uses_parent_name_over_parent_id():
    doc = _make_payment_doc()
    student = {"full_name": "Student One", "parent_id": "firebase-uid-abc"}
    parent_user = {"display_name": "Jane Parent", "user_id": "firebase-uid-abc"}
    row = MongoPaymentRepository._to_admin_row(doc, student, parent_user)
    assert row["parent_name"] == "Jane Parent"


def test_to_admin_row_parent_name_none_when_no_user():
    doc = _make_payment_doc()
    row = MongoPaymentRepository._to_admin_row(doc, None, None)
    assert row["parent_name"] is None
    assert row["parent_id"] == "firebase-uid-abc"
