"""mongomock contract for ``MongoBillingAuditLogRepository.list_for_family``."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.billing.domain.billing_audit import BillingAuditEntry
from backend.v2.contexts.billing.infrastructure.mongo_billing_audit_log import (
    MongoBillingAuditLogRepository,
)

AT = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


def _entry(**overrides: object) -> BillingAuditEntry:
    base: dict[str, object] = dict(
        audit_id="a-1",
        academy_id="test-academy",
        action="manual_payment_recorded",
        actor_id="admin-1",
        at=AT,
    )
    base.update(overrides)
    return BillingAuditEntry(**base)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_list_for_family_matches_invoice_payment_parent_and_enrollment(db, acad) -> None:
    repo = MongoBillingAuditLogRepository(db)
    await repo.append(_entry(audit_id="by-invoice", invoice_id="inv-1"))
    await repo.append(_entry(audit_id="by-payment", action="refund_issued", payment_id="pay-1"))
    await repo.append(
        _entry(audit_id="by-parent", action="autopay_paused", parent_id="p-1", reason="moving")
    )
    await repo.append(
        _entry(
            audit_id="by-enrollment",
            action="autopay_resumed",
            before={"enrollment_id": "e-1", "status": "paused"},
            after={"enrollment_id": "e-1", "status": "active"},
        )
    )
    await repo.append(_entry(audit_id="other", invoice_id="inv-other"))

    entries = await repo.list_for_family(
        parent_id="p-1", invoice_ids=["inv-1"], payment_ids=["pay-1"], enrollment_ids=["e-1"]
    )

    assert sorted(e.audit_id for e in entries) == [
        "by-enrollment",
        "by-invoice",
        "by-parent",
        "by-payment",
    ]
    paused = next(e for e in entries if e.audit_id == "by-parent")
    assert paused.parent_id == "p-1"
    assert paused.reason == "moving"


@pytest.mark.asyncio
async def test_list_for_family_is_tenant_scoped(db, acad) -> None:
    await db["billing_audit_log"].insert_one(
        {
            "audit_id": "foreign",
            "academy_id": "other-academy",
            "action": "autopay_paused",
            "actor_id": "x",
            "at": AT,
            "parent_id": "p-1",
        }
    )
    repo = MongoBillingAuditLogRepository(db)

    entries = await repo.list_for_family(
        parent_id="p-1", invoice_ids=[], payment_ids=[], enrollment_ids=[]
    )

    assert entries == []
