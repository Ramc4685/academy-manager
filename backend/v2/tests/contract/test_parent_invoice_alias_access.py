"""Parent portal invoices reached under any of the parent's own ids (#932).

A parent's invoices may be stamped with any id their ``users`` document
answers to (roster ``user_id``, ``firebase_uid``, ``auth_uid``, ``_id``; People
CRM spec section 1). ``GET /parent/invoices`` and ``GET /parent/invoices/{id}``
used to compare ``invoice.parent_id`` to ``claims.user_id`` exactly, so a
parent whose invoice was stored under their firebase uid saw nothing.

Real ``mongod`` with every migration applied (``real_db``), driven through
``compose_parent``'s use cases, so the 0132 validators and the production
``(academy_id, parent_id, created_at)`` index are the ones in play.

Authorization stays strict (#664: tenant membership is NOT parent
authorization): aliases widen only the identity side of the query, every
invoice read keeps ``academy_id``, and another family's invoice in the same
tenant or the same parent's invoice in another tenant stays invisible.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.composition.parent import compose_parent
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.shared.idempotency.mongo_store import MongoIdempotencyStore
from backend.v2.shared.tenancy.context import tenant_scope

ACAD = "acad-inv-alias-a"
OTHER = "acad-inv-alias-b"
PARENT = "u-inv-alias"
ALIAS = "fb-inv-alias"
OTHER_PARENT = "u-inv-other"
OTHER_PARENT_ALIAS = "fb-inv-other"


class _Outbox:
    async def publish(self, *_a: Any, **_k: Any) -> None:
        return None


def _invoice(
    academy_id: str,
    invoice_id: str,
    *,
    parent_id: str,
    created_at: datetime,
    total: int = 5_000,
) -> dict[str, Any]:
    return {
        "invoice_id": invoice_id,
        "academy_id": academy_id,
        "parent_id": parent_id,
        "student_id": "stu-inv-alias",
        "enrollment_id": "enr-inv-alias",
        "period": "2026-09",
        "status": "open",
        "subtotal_cents": total,
        "discount_cents": 0,
        "total_cents": total,
        "balance_due_cents": total,
        "refunded_cents": 0,
        "currency": "usd",
        "due_date": datetime(2026, 10, 5, tzinfo=UTC),
        "created_at": created_at,
        "updated_at": created_at,
    }


def _at(day: int) -> datetime:
    return datetime(2026, 9, day, 6, 0, tzinfo=UTC)


async def _seed_users(db: Any) -> None:
    await db["users"].insert_many(
        [
            {
                "user_id": PARENT,
                "firebase_uid": ALIAS,
                "academy_id": ACAD,
                "display_name": "Testparent Alias",
                "email": "alias-parent@example.test",
                "roles": ["parent"],
            },
            {
                "user_id": OTHER_PARENT,
                "firebase_uid": OTHER_PARENT_ALIAS,
                "academy_id": ACAD,
                "display_name": "Testparent Other",
                "email": "other-parent@example.test",
                "roles": ["parent"],
            },
        ]
    )


def _parent(db: Any) -> Any:
    return compose_parent(
        db,
        outbox=_Outbox(),  # type: ignore[arg-type]
        idempotency_store=MongoIdempotencyStore(db),
        stripe=FakeStripeGateway(),
        academy_id=ACAD,
    )


@pytest.mark.asyncio
async def test_parent_sees_invoice_stored_under_their_firebase_uid(real_db: Any) -> None:
    await _seed_users(real_db)
    await real_db["invoices"].insert_many(
        [
            _invoice(ACAD, "inv-under-alias", parent_id=ALIAS, created_at=_at(3)),
            _invoice(ACAD, "inv-under-user-id", parent_id=PARENT, created_at=_at(5)),
        ]
    )
    parent = _parent(real_db)

    with tenant_scope(ACAD):
        rows = await parent.list_invoices_for_parent(PARENT)
        detail = await parent.get_invoice_for_parent(parent_id=PARENT, invoice_id="inv-under-alias")

    # Both spellings of the same parent, newest first.
    assert [inv.invoice_id for inv in rows] == ["inv-under-user-id", "inv-under-alias"]
    assert detail is not None
    assert detail["invoice"].invoice_id == "inv-under-alias"


@pytest.mark.asyncio
async def test_parent_reached_under_alias_sees_invoice_stored_under_user_id(
    real_db: Any,
) -> None:
    await _seed_users(real_db)
    await real_db["invoices"].insert_one(
        _invoice(ACAD, "inv-canonical", parent_id=PARENT, created_at=_at(4))
    )
    parent = _parent(real_db)

    with tenant_scope(ACAD):
        rows = await parent.list_invoices_for_parent(ALIAS)
        detail = await parent.get_invoice_for_parent(parent_id=ALIAS, invoice_id="inv-canonical")

    assert [inv.invoice_id for inv in rows] == ["inv-canonical"]
    assert detail is not None
    assert detail["invoice"].invoice_id == "inv-canonical"


@pytest.mark.asyncio
async def test_exact_match_still_works(real_db: Any) -> None:
    await _seed_users(real_db)
    await real_db["invoices"].insert_one(
        _invoice(ACAD, "inv-exact", parent_id=PARENT, created_at=_at(2))
    )
    parent = _parent(real_db)

    with tenant_scope(ACAD):
        rows = await parent.list_invoices_for_parent(PARENT)
        detail = await parent.get_invoice_for_parent(parent_id=PARENT, invoice_id="inv-exact")

    assert [inv.invoice_id for inv in rows] == ["inv-exact"]
    assert detail is not None


@pytest.mark.asyncio
async def test_parent_with_no_users_document_keeps_exact_match(real_db: Any) -> None:
    """No identity row to widen from: behave exactly as before (the id itself)."""
    await real_db["invoices"].insert_one(
        _invoice(ACAD, "inv-orphan-id", parent_id="u-no-users-row", created_at=_at(2))
    )
    parent = _parent(real_db)

    with tenant_scope(ACAD):
        rows = await parent.list_invoices_for_parent("u-no-users-row")
        detail = await parent.get_invoice_for_parent(
            parent_id="u-no-users-row", invoice_id="inv-orphan-id"
        )

    assert [inv.invoice_id for inv in rows] == ["inv-orphan-id"]
    assert detail is not None


@pytest.mark.asyncio
async def test_another_family_in_the_same_tenant_stays_invisible(real_db: Any) -> None:
    """Same tenant is not the same family (#664)."""
    await _seed_users(real_db)
    await real_db["invoices"].insert_many(
        [
            _invoice(ACAD, "inv-mine", parent_id=ALIAS, created_at=_at(2)),
            _invoice(ACAD, "inv-theirs", parent_id=OTHER_PARENT, created_at=_at(3)),
            _invoice(ACAD, "inv-theirs-alias", parent_id=OTHER_PARENT_ALIAS, created_at=_at(4)),
        ]
    )
    parent = _parent(real_db)

    with tenant_scope(ACAD):
        rows = await parent.list_invoices_for_parent(PARENT)
        theirs = await parent.get_invoice_for_parent(parent_id=PARENT, invoice_id="inv-theirs")
        theirs_alias = await parent.get_invoice_for_parent(
            parent_id=PARENT, invoice_id="inv-theirs-alias"
        )

    assert [inv.invoice_id for inv in rows] == ["inv-mine"]
    assert theirs is None
    assert theirs_alias is None


@pytest.mark.asyncio
async def test_same_parent_invoice_in_another_tenant_stays_invisible(real_db: Any) -> None:
    """Aliases widen identity only; every invoice read keeps academy_id."""
    await _seed_users(real_db)
    await real_db["invoices"].insert_many(
        [
            _invoice(ACAD, "inv-here", parent_id=PARENT, created_at=_at(2)),
            _invoice(OTHER, "inv-elsewhere", parent_id=ALIAS, created_at=_at(6)),
            _invoice(OTHER, "inv-elsewhere-canonical", parent_id=PARENT, created_at=_at(7)),
        ]
    )
    parent = _parent(real_db)

    with tenant_scope(ACAD):
        rows = await parent.list_invoices_for_parent(PARENT)
        elsewhere = await parent.get_invoice_for_parent(
            parent_id=PARENT, invoice_id="inv-elsewhere"
        )
        elsewhere_canonical = await parent.get_invoice_for_parent(
            parent_id=ALIAS, invoice_id="inv-elsewhere-canonical"
        )

    assert [inv.invoice_id for inv in rows] == ["inv-here"]
    assert elsewhere is None
    assert elsewhere_canonical is None


@pytest.mark.asyncio
async def test_unknown_parent_gets_empty_list_and_not_found(real_db: Any) -> None:
    await _seed_users(real_db)
    await real_db["invoices"].insert_one(
        _invoice(ACAD, "inv-someone", parent_id=PARENT, created_at=_at(2))
    )
    parent = _parent(real_db)

    with tenant_scope(ACAD):
        rows = await parent.list_invoices_for_parent("u-nobody")
        detail = await parent.get_invoice_for_parent(parent_id="u-nobody", invoice_id="inv-someone")

    assert rows == []
    assert detail is None


@pytest.mark.asyncio
async def test_merged_list_keeps_newest_first_and_the_cap(real_db: Any) -> None:
    """Merging per-alias reads must not break created_at-desc order or the cap."""
    await _seed_users(real_db)
    # Interleave the two spellings so a naive concatenation would be out of order.
    await real_db["invoices"].insert_many(
        [
            _invoice(
                ACAD,
                f"inv-{day:02d}",
                parent_id=ALIAS if day % 2 else PARENT,
                created_at=_at(day),
            )
            for day in range(1, 9)
        ]
    )
    parent = _parent(real_db)
    repo = MongoBillingLedgerRepository(real_db)

    with tenant_scope(ACAD):
        rows = await parent.list_invoices_for_parent(PARENT)
        capped = await repo.list_invoices_for_parent_aliases([PARENT, ALIAS], limit=3)

    assert [inv.invoice_id for inv in rows] == [f"inv-{day:02d}" for day in range(8, 0, -1)]
    assert [inv.invoice_id for inv in capped] == ["inv-08", "inv-07", "inv-06"]
