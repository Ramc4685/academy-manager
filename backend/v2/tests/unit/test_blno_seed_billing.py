"""Unit tests for BLNO seed billing shape."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

from backend.scripts.backfill_p4_legacy_payments import map_legacy_payment


def _load_seed_module() -> ModuleType:
    script_path = Path(__file__).resolve().parents[4] / "scripts" / "dev" / "seed_blno_staging.py"
    spec = importlib.util.spec_from_file_location("seed_blno_staging_for_test", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seed_tuition_payment_doc_maps_to_student_owned_invoice() -> None:
    module = _load_seed_module()
    payment_doc = module.build_student_tuition_payment_doc(
        payment_id="pay_blno_aadhya_jun2026",
        parent_id="parent-aadhya",
        student_id="std_blno_043_aadhya_abhishek",
        enrollment_id="enr_std_blno_043_aadhya__wed_beginner",
        period="2026-06",
        amount_cents=6000,
        status="pending",
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
        updated_at=datetime(2026, 6, 1, tzinfo=UTC),
        stripe_payment_intent_id=None,
        stripe_checkout_session_id=None,
        description="June 2026 tuition",
    )

    mapped = map_legacy_payment(payment_doc)

    assert mapped is not None
    assert mapped["invoice"]["student_id"] == "std_blno_043_aadhya_abhishek"
    assert mapped["invoice"]["enrollment_id"] == "enr_std_blno_043_aadhya__wed_beginner"
    assert mapped["invoice"]["parent_id"] == "parent-aadhya"
    assert mapped["invoice"]["period"] == "2026-06"


def test_blno_seed_resets_parent_billing_customers_before_reseeding() -> None:
    module = _load_seed_module()

    class _Collection:
        def __init__(self) -> None:
            self.delete_filters: list[dict[str, str]] = []

        def delete_many(self, filter_doc: dict[str, str]) -> None:
            self.delete_filters.append(filter_doc)

    class _Db:
        def __init__(self) -> None:
            self.payments = _Collection()
            self.parent_billing_customers = _Collection()
            self.dead_letter_events = _Collection()
            self.outbox_events = _Collection()

    db = _Db()

    module.reset_blno_seed_billing_collections(db)

    assert db.payments.delete_filters == [{"academy_id": module.ACADEMY_ID}]
    assert db.parent_billing_customers.delete_filters == [{"academy_id": module.ACADEMY_ID}]
    assert db.dead_letter_events.delete_filters == [{}]
    assert db.outbox_events.delete_filters == [{}]
