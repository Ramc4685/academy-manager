"""mongomock contract tests for the People CRM family index (spec §1, §3.2, §7 Phase 2).

Wired exactly as ``composition/families_crm.py`` wires it: identity's alias
resolver, enrollment's lifecycle batch and billing's money read model. Covers
alias resolution (a child stored under ``firebase_uid``, users ``_id``,
``auth_uid`` or the legacy ``parent_user_id`` lands in its family), tenant
isolation, staff exclusion, the money numbers agreeing with the Billing tab,
secondary/primary failure handling, and a bounded query count (no N+1).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest
from bson import ObjectId

from backend.v2.composition.families_crm import compose_admin_family_index
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
from backend.v2.contexts.crm.application.family_index import (
    FamilyIndexQuery,
    FamilyIndexUnavailable,
    query_family_index,
    summarize_family_index,
)
from backend.v2.contexts.crm.infrastructure.family_index_read_model import (
    MongoFamilyIndexReadModel,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository
from backend.v2.shared.time.academy_timezone import academy_timezone_lookup

NOW = datetime(2026, 9, 23, 15, 0, tzinfo=UTC)
USER_TWO_OID = ObjectId("65f0000000000000000000a2")


# ---------------------------------------------------------------- counting db


class _CountingCollection:
    def __init__(self, inner: Any, name: str, calls: list[tuple[str, str, Any]]) -> None:
        self._inner = inner
        self._name = name
        self._calls = calls

    def _log(self, op: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        self._calls.append((self._name, op, args[0] if args else kwargs.get("filter")))

    def find(self, *args: Any, **kwargs: Any) -> Any:
        self._log("find", args, kwargs)
        return self._inner.find(*args, **kwargs)

    def find_one(self, *args: Any, **kwargs: Any) -> Any:
        self._log("find_one", args, kwargs)
        return self._inner.find_one(*args, **kwargs)

    def aggregate(self, *args: Any, **kwargs: Any) -> Any:
        self._log("aggregate", args, kwargs)
        return self._inner.aggregate(*args, **kwargs)

    def count_documents(self, *args: Any, **kwargs: Any) -> Any:
        self._log("count_documents", args, kwargs)
        return self._inner.count_documents(*args, **kwargs)

    def __getattr__(self, attr: str) -> Any:
        return getattr(self._inner, attr)


class CountingDb:
    """Records every read a read model issues, to pin "no N+1" and "no $or"."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls: list[tuple[str, str, Any]] = []

    def __getitem__(self, name: str) -> _CountingCollection:
        return _CountingCollection(self._inner[name], name, self.calls)

    def __getattr__(self, attr: str) -> Any:
        return getattr(self._inner, attr)


def _has_or(value: Any) -> bool:
    if isinstance(value, dict):
        return "$or" in value or any(_has_or(v) for v in value.values())
    if isinstance(value, list | tuple):
        return any(_has_or(v) for v in value)
    return False


# ---------------------------------------------------------------- wiring


def _index_model(db: Any, **overrides: Any) -> MongoFamilyIndexReadModel:
    kwargs: dict[str, Any] = {
        "parents": MongoUserRepository(db),
        "children": MongoStudentRepository(db),
        "money": MongoFamilyMoneyReadModel(db),
        "academy_timezone": academy_timezone_lookup(db),
        "clock": lambda: NOW,
    }
    kwargs.update(overrides)
    return MongoFamilyIndexReadModel(db, **kwargs)


def _billing_model(db: Any) -> MongoFamilyBillingReadModel:
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


def _dt(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time(), tzinfo=UTC)


# ---------------------------------------------------------------- seed


async def _seed(db: Any, acad: str) -> None:
    await db["academies"].insert_one({"academy_id": acad, "timezone": "America/Chicago"})
    await db["users"].insert_many(
        [
            {
                "user_id": "u-one",
                "firebase_uid": "fb-one",
                "academy_id": acad,
                "display_name": "Testparent One",
                "email": "one@example.test",
                "phone": "(555) 010-0001",
                "roles": ["parent"],
            },
            {
                # No user_id or auth_uid: the canonical id is the _id itself.
                "_id": USER_TWO_OID,
                "firebase_uid": "fb-two",
                "academy_id": acad,
                "display_name": "Testparent Two",
                "email": "two@example.test",
                "roles": ["parent"],
            },
            {
                "user_id": "u-three",
                "auth_uid": "auth-three",
                "academy_id": acad,
                "display_name": "Testparent Three",
                "email": "three@example.test",
                "roles": ["parent"],
            },
            {
                "user_id": "u-four",
                "academy_id": acad,
                "display_name": "Testparent Four",
                "email": "four@example.test",
                "roles": ["parent"],
            },
            {
                "user_id": "u-coach",
                "academy_id": acad,
                "display_name": "Testcoach Staff",
                "email": "coach@example.test",
                "roles": ["coach"],
            },
        ]
    )
    await db["academy_memberships"].insert_many(
        [
            {"academy_id": acad, "user_id": "u-four", "roles": ["parent"], "status": "active"},
            {"academy_id": acad, "user_id": "u-coach", "roles": ["coach"], "status": "active"},
            {"academy_id": acad, "user_id": "u-gone", "roles": ["parent"], "status": "removed"},
        ]
    )
    await db["students"].insert_many(
        [
            # Family one: one child under the firebase uid, one under user_id.
            {
                "academy_id": acad,
                "student_id": "s-one-a",
                "parent_id": "fb-one",
                "full_name": "Kiddo Onea",
            },
            {
                "academy_id": acad,
                "student_id": "s-one-b",
                "parent_id": "u-one",
                "full_name": "Kiddo Oneb",
            },
            # Family two: stored under the users document _id.
            {
                "academy_id": acad,
                "student_id": "s-two",
                "parent_id": str(USER_TWO_OID),
                "full_name": "Kiddo Two",
            },
            # Family three: legacy parent_user_id holding the auth_uid.
            {
                "academy_id": acad,
                "student_id": "s-three",
                "parent_user_id": "auth-three",
                "full_name": "Kiddo Three",
            },
            # A roster-only parent with no account.
            {
                "academy_id": acad,
                "student_id": "s-roster",
                "parent_id": "roster-only",
                "parent_name": "Rosterguardian Nameonly",
                "full_name": "Kiddo Roster",
            },
            # A child with no family: not in the index.
            {
                "academy_id": acad,
                "student_id": "s-orphan",
                "parent_id": "",
                "full_name": "Kiddo Orphan",
            },
            # Deleted: not in the index.
            {
                "academy_id": acad,
                "student_id": "s-deleted",
                "parent_id": "u-one",
                "full_name": "Kiddo Gone",
                "is_deleted": True,
            },
        ]
    )
    await db["sessions"].insert_many(
        [
            {"academy_id": acad, "session_id": "sess-sat", "title": "Sat Beginners"},
            {"academy_id": acad, "session_id": "sess-wed", "title": "Wed Juniors"},
        ]
    )
    await db["enrollments"].insert_many(
        [
            {
                "academy_id": acad,
                "enrollment_id": "e-1a",
                "student_id": "s-one-a",
                "session_id": "sess-sat",
                "status": "active",
            },
            {
                "academy_id": acad,
                "enrollment_id": "e-1b",
                "student_id": "s-one-b",
                "session_id": "sess-wed",
                "status": "dropped",
            },
            {
                "academy_id": acad,
                "enrollment_id": "e-2",
                "student_id": "s-two",
                "session_id": "sess-wed",
                "status": "paused",
            },
            {
                "academy_id": acad,
                "enrollment_id": "e-3",
                "student_id": "s-three",
                "session_id": "sess-wed",
                "status": "held",
            },
            {
                "academy_id": acad,
                "enrollment_id": "e-r",
                "student_id": "s-roster",
                "session_id": "sess-sat",
                "status": "active",
            },
        ]
    )
    await db["invoices"].insert_many(
        [
            {
                "academy_id": acad,
                "invoice_id": "inv-1",
                "parent_id": "fb-one",
                "student_id": "s-one-a",
                "period": "2026-09",
                "status": "open",
                "total_cents": 6000,
                "balance_due_cents": 6000,
                "due_date": _dt(date(2026, 9, 1)),
                "created_at": datetime(2026, 9, 1, 6, 0, tzinfo=UTC),
            },
            {
                "academy_id": acad,
                "invoice_id": "inv-2",
                "parent_id": "u-one",
                "student_id": "s-one-b",
                "period": "2026-10",
                "status": "partially_paid",
                "total_cents": 3000,
                "balance_due_cents": 1500,
                "due_date": _dt(date(2026, 10, 1)),
                "created_at": datetime(2026, 9, 20, 6, 0, tzinfo=UTC),
            },
            {
                "academy_id": acad,
                "invoice_id": "inv-paid",
                "parent_id": "u-one",
                "period": "2026-08",
                "status": "paid",
                "total_cents": 6000,
                "balance_due_cents": 0,
                "created_at": datetime(2026, 8, 1, 6, 0, tzinfo=UTC),
            },
            {
                "academy_id": acad,
                "invoice_id": "inv-3",
                "parent_user_id": "u-three",
                "period": "2026-09",
                "status": "open",
                "total_cents": 4000,
                "balance_due_cents": 4000,
                "due_date": _dt(date(2026, 9, 30)),
                "created_at": datetime(2026, 9, 1, 6, 0, tzinfo=UTC),
            },
        ]
    )
    await db["parent_billing_customers"].insert_one(
        {
            "academy_id": acad,
            "parent_id": "fb-one",
            "payment_method_label": "Visa",
            "payment_method_last4": "4242",
        }
    )
    await db["payment_attempts"].insert_one(
        {
            "academy_id": acad,
            "attempt_id": "att-1",
            "invoice_id": "inv-1",
            "status": "failed",
            "failure_code": "card_declined",
            "created_at": datetime(2026, 9, 2, 6, 0, tzinfo=UTC),
        }
    )
    # Another academy sharing a parent id and a student id: invisible here.
    await db["students"].insert_one(
        {
            "academy_id": "other-academy",
            "student_id": "s-foreign",
            "parent_id": "fb-one",
            "full_name": "Kiddo Foreign",
        }
    )
    await db["invoices"].insert_one(
        {
            "academy_id": "other-academy",
            "invoice_id": "inv-foreign",
            "parent_id": "fb-one",
            "status": "open",
            "total_cents": 99999,
            "balance_due_cents": 99999,
        }
    )


def _by_id(index: Any) -> dict[str, Any]:
    return {family.family_id: family for family in index.families}


# ---------------------------------------------------------------- tests


@pytest.mark.asyncio
async def test_every_alias_lands_in_one_family_per_parent(db, acad) -> None:
    await _seed(db, acad)
    index = await _index_model(db).build(acad)
    families = _by_id(index)

    assert set(families) == {"u-one", str(USER_TWO_OID), "u-three", "u-four", "roster-only"}
    one = families["u-one"]
    assert [c.student_id for c in one.children] == ["s-one-a", "s-one-b"]
    assert one.parent_name == "Testparent One"
    assert one.has_account is True
    assert one.stage == "active"  # split family: active beats left
    assert [c.lifecycle for c in one.children] == ["active", "left"]
    assert one.children[0].session_titles == ("Sat Beginners",)
    assert families[str(USER_TWO_OID)].stage == "paused"
    assert families["u-three"].stage == "on_hold"
    assert families["u-four"].stage == "never_enrolled"
    assert families["u-four"].children == ()
    roster = families["roster-only"]
    assert roster.has_account is False
    assert roster.parent_name == "Rosterguardian Nameonly"
    assert index.warnings == ()


@pytest.mark.asyncio
async def test_staff_orphans_deleted_and_other_tenants_are_excluded(db, acad) -> None:
    await _seed(db, acad)
    index = await _index_model(db).build(acad)
    ids = {c.student_id for f in index.families for c in f.children}
    assert "s-orphan" not in ids
    assert "s-deleted" not in ids
    assert "s-foreign" not in ids
    assert "u-coach" not in _by_id(index)
    assert "u-gone" not in _by_id(index)


@pytest.mark.asyncio
async def test_money_is_grouped_across_aliases_and_ignores_other_tenants(db, acad) -> None:
    await _seed(db, acad)
    families = _by_id(await _index_model(db).build(acad))
    one = families["u-one"]
    assert one.money is not None
    assert one.money.balance_cents == 7500
    assert one.money.open_invoice_count == 2
    assert one.money.overdue_invoice_count == 1
    assert one.money.overdue_cents == 6000
    assert one.money.oldest_overdue_due_on == date(2026, 9, 1)
    assert one.money.last_failed_payment_at == datetime(2026, 9, 2, 6, 0, tzinfo=UTC)
    assert one.card_on_file is True
    assert one.registration == "registered"
    three = families["u-three"]
    assert three.money is not None and three.money.balance_cents == 4000
    assert three.card_on_file is False


@pytest.mark.asyncio
async def test_list_and_billing_tab_agree_for_a_child_stored_under_firebase_uid(db, acad) -> None:
    """Spec §7 Phase 2: the list and the Billing tab show the same family."""
    await _seed(db, acad)
    index = await _index_model(db).build(acad)
    row = _by_id(index)["u-one"]
    assert row.money is not None

    for opened_as in ("u-one", "fb-one"):
        view = await _billing_model(db).build(opened_as)
        assert view is not None, opened_as
        assert view["header"]["balance_cents"] == row.money.balance_cents
        assert view["header"]["open_invoice_count"] == row.money.open_invoice_count
        assert {s["student_id"] for s in view["students"]} == {c.student_id for c in row.children}
        assert view["header"]["registration"]["card_on_file"] is True
        assert "inv-foreign" not in {i["invoice_id"] for i in view["invoices"]}

    # The legacy parent_user_id invoice reaches the Billing tab too.
    three = await _billing_model(db).build("auth-three")
    assert three is not None
    assert three["header"]["balance_cents"] == 4000


@pytest.mark.asyncio
async def test_no_read_uses_an_or_across_fields(db, acad) -> None:
    """#894: every parent lookup is an equality (or $in) on ONE field."""
    await _seed(db, acad)
    counting = CountingDb(db)
    await _index_model(counting).build(acad)
    await _billing_model(counting).build("fb-one")
    offenders = [
        (coll, op, flt)
        for coll, op, flt in counting.calls
        if coll in {"users", "students", "invoices", "parent_billing_customers"} and _has_or(flt)
    ]
    assert offenders == []


async def _seed_many(db: Any, acad: str, n: int) -> None:
    await db["academies"].insert_one({"academy_id": acad, "timezone": "UTC"})
    for i in range(n):
        uid = f"u-{i}"
        await db["users"].insert_one(
            {
                "user_id": uid,
                "firebase_uid": f"fb-{i}",
                "display_name": f"Testparent N{i}",
                "roles": ["parent"],
            }
        )
        await db["students"].insert_one(
            {
                "academy_id": acad,
                "student_id": f"s-{i}",
                "parent_id": f"fb-{i}" if i % 2 else uid,
                "full_name": f"Kid N{i}",
            }
        )
        await db["enrollments"].insert_one(
            {
                "academy_id": acad,
                "enrollment_id": f"e-{i}",
                "student_id": f"s-{i}",
                "session_id": "sess",
                "status": "active",
            }
        )
        await db["invoices"].insert_one(
            {
                "academy_id": acad,
                "invoice_id": f"inv-{i}",
                "parent_id": uid,
                "status": "open",
                "balance_due_cents": 100,
                "total_cents": 100,
            }
        )
        await db["parent_billing_customers"].insert_one({"academy_id": acad, "parent_id": uid})
    await db["sessions"].insert_one({"academy_id": acad, "session_id": "sess", "title": "Class"})


@pytest.mark.asyncio
async def test_query_count_is_fixed_however_many_families(acad) -> None:
    """No N+1: 3 families and 30 families cost the same number of reads."""
    import mongomock_motor

    counts = []
    for n in (3, 30):
        raw = mongomock_motor.AsyncMongoMockClient()[f"n{n}"]
        await _seed_many(raw, acad, n)
        counting = CountingDb(raw)
        index = await _index_model(counting).build(acad)
        assert len(index.families) == n
        assert all(f.money is not None and f.money.balance_cents == 100 for f in index.families)
        counts.append(len(counting.calls))
    assert counts[0] == counts[1]
    assert counts[1] <= 14, counts


@pytest.mark.asyncio
async def test_money_failure_is_a_warning_not_a_zero(db, acad) -> None:
    await _seed(db, acad)

    class BrokenMoney:
        async def summaries(self, **_: Any) -> Any:
            raise RuntimeError("billing down")

    index = await _index_model(db, money=BrokenMoney()).build(acad)
    assert index.warnings == ("money_unavailable",)
    one = _by_id(index)["u-one"]
    assert one.money is None
    assert one.card_on_file is None
    assert one.stage == "active"


@pytest.mark.asyncio
async def test_primary_source_failure_raises(db, acad) -> None:
    await _seed(db, acad)

    class BrokenParents:
        async def resolve_parent_aliases(self, raw_ids: Any) -> Any:
            raise RuntimeError("users down")

    with pytest.raises(FamilyIndexUnavailable):
        await _index_model(db, parents=BrokenParents()).build(acad)


@pytest.mark.asyncio
async def test_build_is_cached_per_academy_for_the_ttl(db, acad) -> None:
    await _seed(db, acad)
    ticks = [0.0]
    model = _index_model(db, cache_ttl_seconds=60.0, monotonic=lambda: ticks[0])
    first = await model.build(acad)
    await db["students"].insert_one(
        {"academy_id": acad, "student_id": "s-new", "parent_id": "u-four", "full_name": "Kiddo New"}
    )
    assert await model.build(acad) is first
    ticks[0] = 61.0
    fresh = await model.build(acad)
    assert fresh is not first
    assert [c.student_id for c in _by_id(fresh)["u-four"].children] == ["s-new"]


@pytest.mark.asyncio
async def test_composed_index_serves_search_class_filter_and_summary(db, acad) -> None:
    await _seed(db, acad)
    services = compose_admin_family_index(db)
    index = await services.index.build(acad)

    page = query_family_index(index, FamilyIndexQuery(search="kiddo onea"), money_visible=True)
    assert [r.record.family_id for r in page.rows] == ["u-one"]
    assert page.rows[0].hit is not None
    assert page.rows[0].hit.matched_student_ids == ("s-one-a",)

    page = query_family_index(index, FamilyIndexQuery(class_id="sess-sat"), money_visible=True)
    assert {r.record.family_id for r in page.rows} == {"u-one", "roster-only"}

    page = query_family_index(index, FamilyIndexQuery(search="555-010-0001"), money_visible=True)
    assert [r.record.family_id for r in page.rows] == ["u-one"]

    summary = summarize_family_index(index)
    assert summary.total_families == 5
    assert summary.tiles == {"active": 2, "leaving": 2, "left": 0}
