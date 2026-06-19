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
