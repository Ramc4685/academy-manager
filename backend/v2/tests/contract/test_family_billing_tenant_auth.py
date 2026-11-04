"""Who may see a family's money: tenant isolation and parent authorization.

Filters only, so mongomock enforces what is under test (equality on
``academy_id`` and on the parent reference); no uniqueness, partial index or
concurrency is involved. Covers:

* academy B cannot read academy A's family on the Billing tab or in the family
  list, whether it asks by the canonical user id or by an alias (spec §1);
* tenant membership is not parent authorization (#664 class): a staff member
  with a membership in the academy, and even invoices stored under their id,
  gets no family billing;
* the parent persona sees only their own invoices: another parent of the SAME
  academy is a 404 on the invoice and absent from the list.

Cross-tenant RECORDING is covered on a real mongod in
``test_record_manual_payment_money_path.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.composition.parent import compose_parent
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.contexts.billing.infrastructure.family_billing_read_model import (
    MongoFamilyBillingReadModel,
)
from backend.v2.contexts.billing.infrastructure.family_money_read_model import (
    MongoFamilyMoneyReadModel,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_audit_log import (
    MongoBillingAuditLogRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_connected_account_repo import (
    MongoConnectedAccountRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_credit_ledger_repo import (
    MongoCreditLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_parent_billing_customer_repo import (
    MongoParentBillingCustomerRepository,
)
from backend.v2.contexts.crm.infrastructure.family_index_read_model import (
    MongoFamilyIndexReadModel,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository
from backend.v2.shared.idempotency.mongo_store import MongoIdempotencyStore
from backend.v2.shared.tenancy.context import tenant_scope
from backend.v2.shared.time.academy_timezone import academy_timezone_lookup

ACAD_A = "acad-auth-a"
ACAD_B = "acad-auth-b"
NOW = datetime(2026, 9, 23, 15, 0, tzinfo=UTC)


def _billing_tab(db: Any) -> MongoFamilyBillingReadModel:
    return MongoFamilyBillingReadModel(
        db,
        academy_timezone=academy_timezone_lookup(db),
        connected_accounts=MongoConnectedAccountRepository(db),
        billing_settings=MongoBillingSettingsRepository(db),
        customers=MongoParentBillingCustomerRepository(db),
        credits=MongoCreditLedgerRepository(db),
        users=MongoUserRepository(db),
        audit=MongoBillingAuditLogRepository(db),
        clock=lambda: NOW,
    )


def _family_list(db: Any) -> MongoFamilyIndexReadModel:
    return MongoFamilyIndexReadModel(
        db,
        parents=MongoUserRepository(db),
        children=MongoStudentRepository(db),
        money=MongoFamilyMoneyReadModel(db),
        academy_timezone=academy_timezone_lookup(db),
        clock=lambda: NOW,
    )


def _invoice(academy_id: str, invoice_id: str, parent_id: str, total: int) -> dict[str, Any]:
    return {
        "invoice_id": invoice_id,
        "academy_id": academy_id,
        "parent_id": parent_id,
        "student_id": f"stu-{parent_id}",
        "period": "2026-09",
        "status": "open",
        "subtotal_cents": total,
        "discount_cents": 0,
        "total_cents": total,
        "balance_due_cents": total,
        "currency": "usd",
        "due_date": datetime(2026, 10, 1, tzinfo=UTC),
        "created_at": NOW,
        "updated_at": NOW,
    }


async def _seed_parent(
    db: Any, academy_id: str, user_id: str, *, alias: str, balance: int, invoice_id: str
) -> None:
    await db["users"].insert_one(
        {
            "user_id": user_id,
            "firebase_uid": alias,
            "academy_id": academy_id,
            "display_name": f"Testparent {user_id}",
            "email": f"{user_id}@example.test",
            "roles": ["parent"],
        }
    )
    await db["students"].insert_one(
        {
            "academy_id": academy_id,
            "student_id": f"stu-{user_id}",
            # Stored under the alias, the shape spec §1 exists for.
            "parent_id": alias,
            "full_name": f"Testchild {user_id}",
            "status": "active",
        }
    )
    await db["invoices"].insert_one(_invoice(academy_id, invoice_id, user_id, balance))


async def _two_academies(db: Any) -> None:
    for acad in (ACAD_A, ACAD_B):
        await db["academies"].insert_one({"academy_id": acad, "timezone": "America/Chicago"})
    await _seed_parent(db, ACAD_A, "u-auth-a", alias="fb-auth-a", balance=6_000, invoice_id="inv-a")
    await _seed_parent(db, ACAD_B, "u-auth-b", alias="fb-auth-b", balance=2_000, invoice_id="inv-b")


# ------------------------------------------------------------------ cross-tenant


@pytest.mark.asyncio
@pytest.mark.parametrize("asked_as", ["u-auth-a", "fb-auth-a"], ids=["canonical", "alias"])
async def test_other_academy_cannot_open_this_familys_billing(db, asked_as: str) -> None:
    await _two_academies(db)
    with tenant_scope(ACAD_A):
        assert await _billing_tab(db).build(asked_as) is not None
    with tenant_scope(ACAD_B):
        assert await _billing_tab(db).build(asked_as) is None


@pytest.mark.asyncio
async def test_family_list_holds_only_its_own_academys_families_and_money(db) -> None:
    await _two_academies(db)
    with tenant_scope(ACAD_B):
        index = await _family_list(db).build(ACAD_B)

    families = {f.family_id: f for f in index.families}
    assert set(families) == {"u-auth-b"}
    money = families["u-auth-b"].money
    assert money is not None and money.balance_cents == 2_000


@pytest.mark.asyncio
async def test_same_parent_id_in_two_academies_never_mixes_money(db) -> None:
    """The #849 shape: ids copied between academies collide; money must not."""
    await _two_academies(db)
    # Academy B holds an invoice under academy A's parent id.
    await db["invoices"].insert_one(_invoice(ACAD_B, "inv-collide", "u-auth-a", 9_900))
    with tenant_scope(ACAD_A):
        view = await _billing_tab(db).build("u-auth-a")
        index = await _family_list(db).build(ACAD_A)

    assert view is not None
    assert {i["invoice_id"] for i in view["invoices"]} == {"inv-a"}
    assert view["header"]["balance_cents"] == 6_000
    row = next(f for f in index.families if f.family_id == "u-auth-a")
    assert row.money is not None and row.money.balance_cents == 6_000


# ------------------------------------------------------------------ membership is not parenthood


@pytest.mark.asyncio
@pytest.mark.parametrize("roles", [["admin"], ["coach"], ["owner", "admin"]])
async def test_staff_member_with_invoices_under_their_id_gets_no_family_billing(
    db, roles: list[str]
) -> None:
    """#664 class: tenant membership passes a naive check; it is not a parent relation."""
    await db["academies"].insert_one({"academy_id": ACAD_A, "timezone": "America/Chicago"})
    await db["users"].insert_one(
        {
            "user_id": "u-staff",
            "academy_id": ACAD_A,
            "display_name": "Teststaff Member",
            "email": "staff@example.test",
            "roles": roles,
        }
    )
    await db["academy_memberships"].insert_one(
        {"academy_id": ACAD_A, "user_id": "u-staff", "roles": roles}
    )
    await db["invoices"].insert_one(_invoice(ACAD_A, "inv-staff", "u-staff", 4_200))

    with tenant_scope(ACAD_A):
        assert await _billing_tab(db).build("u-staff") is None
        index = await _family_list(db).build(ACAD_A)

    assert "u-staff" not in {f.family_id for f in index.families}


# ------------------------------------------------------------------ parent persona


class _FakeOutbox:
    async def append(self, event: object) -> None:
        return None


@pytest.mark.asyncio
async def test_parent_sees_only_their_own_invoices_in_their_own_academy(db) -> None:
    await _two_academies(db)
    # A second parent in academy A: same tenant, different family.
    await _seed_parent(
        db, ACAD_A, "u-auth-a2", alias="fb-auth-a2", balance=1_500, invoice_id="inv-a2"
    )
    parent = compose_parent(
        db,
        _FakeOutbox(),  # type: ignore[arg-type]
        MongoIdempotencyStore(db),
        FakeStripeGateway(),
        academy_id=ACAD_A,
    )
    with tenant_scope(ACAD_A):
        own = await parent.list_invoices_for_parent("u-auth-a2")
        mine = await parent.get_invoice_for_parent(parent_id="u-auth-a2", invoice_id="inv-a2")
        theirs = await parent.get_invoice_for_parent(parent_id="u-auth-a2", invoice_id="inv-a")
    with tenant_scope(ACAD_B):
        cross = await parent.get_invoice_for_parent(parent_id="u-auth-a", invoice_id="inv-a")
        cross_list = await parent.list_invoices_for_parent("u-auth-a")

    assert [i.invoice_id for i in own] == ["inv-a2"]
    assert mine is not None
    assert theirs is None
    assert cross is None
    assert cross_list == []
