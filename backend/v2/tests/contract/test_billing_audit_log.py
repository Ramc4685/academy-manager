"""P0-4: billing audit log — append-only, tenant-scoped, queryable by invoice."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.billing.domain.billing_audit import BillingAuditEntry
from backend.v2.contexts.billing.infrastructure.mongo_billing_audit_log import (
    MongoBillingAuditLogRepository,
)
from backend.v2.shared.tenancy import tenant_scope

NOW = datetime(2026, 6, 20, 10, 0, tzinfo=UTC)


def _entry(audit_id: str, academy_id: str, **kw) -> BillingAuditEntry:
    return BillingAuditEntry(
        audit_id=audit_id,
        academy_id=academy_id,
        action=kw.get("action", "refund_issued"),
        actor_id=kw.get("actor_id", "admin-1"),
        at=NOW,
        invoice_id=kw.get("invoice_id", "inv-1"),
        payment_id=kw.get("payment_id"),
        reason=kw.get("reason"),
        before=kw.get("before"),
        after=kw.get("after"),
    )


@pytest.mark.asyncio
async def test_append_and_list_for_invoice(db, acad) -> None:
    repo = MongoBillingAuditLogRepository(db)
    await repo.append(
        _entry(
            "a1",
            acad,
            action="refund_issued",
            actor_id="admin-7",
            payment_id="pay-1",
            reason="duplicate",
            before={"refunded_cents": 0},
            after={"refunded_cents": 500},
        )
    )
    rows = await repo.list_for_invoice("inv-1")
    assert len(rows) == 1
    assert rows[0].actor_id == "admin-7"
    assert rows[0].action == "refund_issued"
    assert rows[0].after == {"refunded_cents": 500}


@pytest.mark.asyncio
async def test_audit_log_is_tenant_scoped(db, acad) -> None:
    repo = MongoBillingAuditLogRepository(db)
    await repo.append(_entry("a1", acad, invoice_id="inv-1"))
    with tenant_scope("other-academy"):
        other = MongoBillingAuditLogRepository(db)
        assert await other.list_for_invoice("inv-1") == []


@pytest.mark.asyncio
async def test_audit_log_is_append_only(db, acad) -> None:
    repo = MongoBillingAuditLogRepository(db)
    await repo.append(_entry("a1", acad, invoice_id="inv-1", action="refund_issued"))
    await repo.append(_entry("a2", acad, invoice_id="inv-1", action="manual_payment_recorded"))
    rows = await repo.list_for_invoice("inv-1")
    assert {r.audit_id for r in rows} == {"a1", "a2"}
    # repo exposes no update/delete API
    assert not hasattr(repo, "update") and not hasattr(repo, "delete")
