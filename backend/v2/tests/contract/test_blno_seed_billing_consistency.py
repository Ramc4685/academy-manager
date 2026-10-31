"""The BLNO staging seed must write a ledger the launch-readiness audit accepts.

Issue #594: `saas_staging.sh blno-seed` exited non-zero because it ran the
launch-readiness audit and let the audit's status become the seed's exit code.
The script hygiene is fixed in `scripts/dev/saas_staging.sh` (and covered by
`scripts/dev/saas_staging_test.sh`); this test pins the other half of the
question the issue asked — whether the seed's own invoice/allocation/credit
rows actually satisfy `audit_billing_consistency`'s invariants.

The seed writes ledger rows in exactly one place,
`seed_blno_staging._upsert_ledger_from_seed_payment`, so we drive that function
with every payment shape the seed produces, replay its writes into an
in-process Mongo, and assert the audit reports no billing failures.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from backend.scripts.launch_readiness_audit import audit_billing_consistency


def _load_seed_module() -> ModuleType:
    script_path = Path(__file__).resolve().parents[4] / "scripts" / "dev" / "seed_blno_staging.py"
    spec = importlib.util.spec_from_file_location("seed_blno_staging_for_test", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _RecordingCollection:
    """Captures the seed's synchronous upserts so we can replay them async."""

    def __init__(self, name: str, writes: list[tuple[str, dict[str, Any]]]) -> None:
        self._name = name
        self._writes = writes

    def update_one(
        self, _filter: dict[str, Any], update: dict[str, Any], upsert: bool = False
    ) -> None:
        assert upsert is True, "seed ledger writes must be upserts"
        self._writes.append((self._name, dict(update["$set"])))


class _RecordingDb:
    def __init__(self) -> None:
        self.writes: list[tuple[str, dict[str, Any]]] = []

    def __getattr__(self, name: str) -> _RecordingCollection:
        return _RecordingCollection(name, self.writes)


def _seed_payment_variants(module: ModuleType) -> list[dict[str, Any]]:
    """One payment doc per shape `seed_blno_staging` emits for a student.

    April is always `succeeded`; May cycles succeeded / pending / failed; June
    is always `pending`. Amounts vary per family, so a couple of odd ones are
    included alongside the common flat rates.
    """
    created = dt.datetime(2026, 4, 1, tzinfo=dt.UTC)
    updated = dt.datetime(2026, 4, 5, tzinfo=dt.UTC)
    variants: list[dict[str, Any]] = []
    for index, (status, amount_cents, intent) in enumerate(
        [
            ("succeeded", 12_000, "pi_blno_0001"),
            ("succeeded", 6_500, "pi_blno_0002"),
            ("pending", 12_000, None),
            ("failed", 9_999, "pi_blno_0003"),
            ("pending", 1, None),
        ]
    ):
        variants.append(
            module.build_student_tuition_payment_doc(
                payment_id=f"pay_blno_case_{index}",
                parent_id=f"parent-{index}",
                student_id=f"std_blno_{index:03d}",
                enrollment_id=f"enr_std_blno_{index:03d}__wed_beginner",
                period="2026-04",
                amount_cents=amount_cents,
                status=status,
                created_at=created,
                updated_at=updated,
                stripe_payment_intent_id=intent,
                stripe_checkout_session_id=f"cs_blno_{index:04d}" if intent else None,
                description="April 2026 tuition",
            )
        )
    return variants


@pytest.mark.asyncio
async def test_blno_seed_ledger_rows_satisfy_billing_consistency_invariants(db) -> None:
    module = _load_seed_module()
    recorder = _RecordingDb()

    for payment_doc in _seed_payment_variants(module):
        module._upsert_ledger_from_seed_payment(recorder, payment_doc)

    assert recorder.writes, "the seed must write ledger rows for these payments"
    for collection_name, doc in recorder.writes:
        await db[collection_name].insert_one(doc)

    result = await audit_billing_consistency(db, primary_academy_id=module.ACADEMY_ID)

    assert result["failures"] == []
    assert result["status"] == "pass"
    assert result["invoice_count"] == 5


@pytest.mark.asyncio
async def test_billing_consistency_still_catches_a_broken_seed_invoice(db) -> None:
    """Guard the guard: the audit must fail on a ledger the seed must not write."""
    module = _load_seed_module()
    recorder = _RecordingDb()
    module._upsert_ledger_from_seed_payment(recorder, _seed_payment_variants(module)[0])

    for collection_name, doc in recorder.writes:
        if collection_name == "invoices":
            doc = {**doc, "balance_due_cents": doc["balance_due_cents"] + 500}
        await db[collection_name].insert_one(doc)

    result = await audit_billing_consistency(db, primary_academy_id=module.ACADEMY_ID)

    assert result["status"] == "fail"
    assert {failure["check"] for failure in result["failures"]} == {
        "invoice_balance_mismatch",
        "paid_invoice_has_balance",
    }
