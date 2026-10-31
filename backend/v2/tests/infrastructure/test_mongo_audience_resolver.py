"""Mongo audience resolver membership lookups."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.v2.contexts.communications.domain.models import (
    AcademyAudience,
    PaymentRiskAudience,
    SessionAudience,
)
from backend.v2.contexts.communications.infrastructure.mongo_audience_resolver import (
    SESSION_AUDIENCE_ENROLLMENT_STATUSES,
    MongoAudienceResolver,
)
from backend.v2.contexts.enrollment.domain.models import ENROLLMENT_STATUSES, ROSTER_VISIBLE
from backend.v2.shared.tenancy.context import tenant_scope
from mongomock_motor import AsyncMongoMockClient


async def test_academy_coach_audience_uses_active_memberships_for_global_users() -> None:
    db = AsyncMongoMockClient()["audience-resolver-memberships"]
    await db["users"].insert_many(
        [
            {
                "user_id": "coach-1",
                "email": "coach@example.com",
                "display_name": "Coach One",
            },
            {
                "user_id": "parent-1",
                "email": "parent@example.com",
                "display_name": "Parent One",
            },
            {
                "user_id": "inactive-coach",
                "email": "inactive@example.com",
                "display_name": "Inactive Coach",
            },
        ]
    )
    await db["academy_memberships"].insert_many(
        [
            {
                "academy_id": "acad-1",
                "user_id": "coach-1",
                "roles": ["coach"],
                "status": "active",
            },
            {
                "academy_id": "acad-1",
                "user_id": "parent-1",
                "roles": ["parent"],
                "status": "active",
            },
            {
                "academy_id": "acad-1",
                "user_id": "inactive-coach",
                "roles": ["coach"],
                "status": "inactive",
            },
            {
                "academy_id": "acad-2",
                "user_id": "other-coach",
                "roles": ["coach"],
                "status": "active",
            },
        ]
    )

    with tenant_scope("acad-1"):
        recipients = await MongoAudienceResolver(db).resolve_academy_audience(
            AcademyAudience(role="coach")
        )

    assert [recipient.user_id for recipient in recipients] == ["coach-1"]
    assert recipients[0].email == "coach@example.com"


async def test_academy_audience_scopes_multi_academy_users_to_current_tenant() -> None:
    """A parent with one user doc per academy must resolve to exactly one
    recipient, carrying the current academy's email — not the other tenant's."""
    db = AsyncMongoMockClient()["audience-resolver-multi-academy"]
    await db["users"].insert_many(
        [
            {
                "user_id": "parent-multi",
                "academy_id": "acad-1",
                "email": "parent@acad-one.com",
                "display_name": "Parent Multi (A1)",
            },
            {
                "user_id": "parent-multi",
                "academy_id": "acad-2",
                "email": "stale@acad-two.com",
                "display_name": "Parent Multi (A2)",
            },
        ]
    )
    await db["academy_memberships"].insert_many(
        [
            {
                "academy_id": "acad-1",
                "user_id": "parent-multi",
                "roles": ["parent"],
                "status": "active",
            },
            {
                "academy_id": "acad-2",
                "user_id": "parent-multi",
                "roles": ["parent"],
                "status": "active",
            },
        ]
    )

    with tenant_scope("acad-1"):
        recipients = await MongoAudienceResolver(db).resolve_academy_audience(
            AcademyAudience(role="parent")
        )

    assert [recipient.user_id for recipient in recipients] == ["parent-multi"]
    assert recipients[0].email == "parent@acad-one.com"


async def test_academy_audience_prefers_tenant_doc_over_global_doc() -> None:
    db = AsyncMongoMockClient()["audience-resolver-tenant-preference"]
    await db["users"].insert_many(
        [
            {
                "user_id": "coach-1",
                "email": "global@example.com",
                "display_name": "Global Doc",
            },
            {
                "user_id": "coach-1",
                "academy_id": "acad-1",
                "email": "tenant@example.com",
                "display_name": "Tenant Doc",
            },
        ]
    )
    await db["academy_memberships"].insert_one(
        {
            "academy_id": "acad-1",
            "user_id": "coach-1",
            "roles": ["coach"],
            "status": "active",
        }
    )

    with tenant_scope("acad-1"):
        recipients = await MongoAudienceResolver(db).resolve_academy_audience(
            AcademyAudience(role="coach")
        )

    assert [recipient.user_id for recipient in recipients] == ["coach-1"]
    assert recipients[0].email == "tenant@example.com"


async def test_payment_risk_audience_scopes_multi_academy_users_to_current_tenant() -> None:
    db = AsyncMongoMockClient()["audience-resolver-payment-risk-multi"]
    now = datetime.now(UTC)
    await db["users"].insert_many(
        [
            {
                "user_id": "parent-multi",
                "academy_id": "acad-1",
                "email": "parent@acad-one.com",
                "display_name": "Parent Multi (A1)",
            },
            {
                "user_id": "parent-multi",
                "academy_id": "acad-2",
                "email": "stale@acad-two.com",
                "display_name": "Parent Multi (A2)",
            },
        ]
    )
    await db["academy_memberships"].insert_one(
        {
            "academy_id": "acad-1",
            "user_id": "parent-multi",
            "roles": ["parent"],
            "status": "active",
        }
    )
    await db["invoices"].insert_one(
        {
            "academy_id": "acad-1",
            "invoice_id": "inv-overdue",
            "parent_id": "parent-multi",
            "status": "open",
            "total_cents": 1000,
            "balance_due_cents": 1000,
            "due_date": now - timedelta(days=10),
            "created_at": now - timedelta(days=20),
        }
    )

    with tenant_scope("acad-1"):
        recipients = await MongoAudienceResolver(db).resolve_payment_risk_audience(
            PaymentRiskAudience(min_days_overdue=7)
        )

    assert [recipient.user_id for recipient in recipients] == ["parent-multi"]
    assert recipients[0].email == "parent@acad-one.com"


async def test_payment_risk_audience_includes_membershipless_tenant_users() -> None:
    """A delinquent parent with a tenant-scoped user doc but no active
    academy_memberships doc must still be resolved (#520 review): the fix is
    academy scoping and dedup, not dropping membership-less tenant users."""
    db = AsyncMongoMockClient()["audience-resolver-payment-risk-membershipless"]
    now = datetime.now(UTC)
    await db["users"].insert_many(
        [
            {
                "user_id": "parent-member",
                "academy_id": "acad-1",
                "email": "member@example.com",
                "display_name": "Member Parent",
            },
            {
                "user_id": "parent-no-membership",
                "academy_id": "acad-1",
                "email": "no-membership@example.com",
                "display_name": "Membership-less Parent",
            },
            {
                "user_id": "parent-other-academy",
                "academy_id": "acad-2",
                "email": "other@example.com",
                "display_name": "Other Academy Parent",
            },
        ]
    )
    await db["academy_memberships"].insert_one(
        {
            "academy_id": "acad-1",
            "user_id": "parent-member",
            "roles": ["parent"],
            "status": "active",
        }
    )
    overdue_invoice = {
        "academy_id": "acad-1",
        "status": "open",
        "total_cents": 1000,
        "balance_due_cents": 1000,
        "due_date": now - timedelta(days=10),
        "created_at": now - timedelta(days=20),
    }
    await db["invoices"].insert_many(
        [
            {**overdue_invoice, "invoice_id": "inv-1", "parent_id": "parent-member"},
            {**overdue_invoice, "invoice_id": "inv-2", "parent_id": "parent-no-membership"},
            {**overdue_invoice, "invoice_id": "inv-3", "parent_id": "parent-other-academy"},
        ]
    )

    with tenant_scope("acad-1"):
        recipients = await MongoAudienceResolver(db).resolve_payment_risk_audience(
            PaymentRiskAudience(min_days_overdue=7)
        )

    assert {recipient.user_id for recipient in recipients} == {
        "parent-member",
        "parent-no-membership",
    }


async def test_payment_risk_audience_uses_overdue_ledger_invoices() -> None:
    db = AsyncMongoMockClient()["audience-resolver-payment-risk"]
    now = datetime.now(UTC)
    await db["users"].insert_many(
        [
            {
                "user_id": "parent-overdue",
                "email": "overdue@example.com",
                "display_name": "Overdue Parent",
            },
            {
                "user_id": "parent-current",
                "email": "current@example.com",
                "display_name": "Current Parent",
            },
        ]
    )
    await db["academy_memberships"].insert_many(
        [
            {
                "academy_id": "acad-1",
                "user_id": "parent-overdue",
                "roles": ["parent"],
                "status": "active",
            },
            {
                "academy_id": "acad-1",
                "user_id": "parent-current",
                "roles": ["parent"],
                "status": "active",
            },
        ]
    )
    await db["invoices"].insert_many(
        [
            {
                "academy_id": "acad-1",
                "invoice_id": "inv-overdue",
                "parent_id": "parent-overdue",
                "status": "open",
                "total_cents": 1000,
                "balance_due_cents": 1000,
                "due_date": now - timedelta(days=10),
                "created_at": now - timedelta(days=20),
            },
            {
                "academy_id": "acad-1",
                "invoice_id": "inv-current",
                "parent_id": "parent-current",
                "status": "open",
                "total_cents": 1000,
                "balance_due_cents": 1000,
                "due_date": now + timedelta(days=5),
                "created_at": now,
            },
        ]
    )

    with tenant_scope("acad-1"):
        recipients = await MongoAudienceResolver(db).resolve_payment_risk_audience(
            PaymentRiskAudience(min_days_overdue=7)
        )

    assert [recipient.user_id for recipient in recipients] == ["parent-overdue"]
    assert recipients[0].email == "overdue@example.com"


async def test_payment_risk_audience_excludes_draft_invoices() -> None:
    """Draft invoices are not payable, so their parents must not be dunned."""
    db = AsyncMongoMockClient()["audience-resolver-payment-risk-draft"]
    now = datetime.now(UTC)
    await db["users"].insert_many(
        [
            {
                "user_id": "parent-draft",
                "email": "draft@example.com",
                "display_name": "Draft Parent",
            },
            {
                "user_id": "parent-open",
                "email": "open@example.com",
                "display_name": "Open Parent",
            },
        ]
    )
    await db["academy_memberships"].insert_many(
        [
            {
                "academy_id": "acad-1",
                "user_id": "parent-draft",
                "roles": ["parent"],
                "status": "active",
            },
            {
                "academy_id": "acad-1",
                "user_id": "parent-open",
                "roles": ["parent"],
                "status": "active",
            },
        ]
    )
    await db["invoices"].insert_many(
        [
            {
                "academy_id": "acad-1",
                "invoice_id": "inv-draft-overdue",
                "parent_id": "parent-draft",
                "status": "draft",
                "total_cents": 1000,
                "balance_due_cents": 1000,
                "due_date": now - timedelta(days=30),
                "created_at": now - timedelta(days=40),
            },
            {
                "academy_id": "acad-1",
                "invoice_id": "inv-open-overdue",
                "parent_id": "parent-open",
                "status": "open",
                "total_cents": 1000,
                "balance_due_cents": 1000,
                "due_date": now - timedelta(days=30),
                "created_at": now - timedelta(days=40),
            },
        ]
    )

    with tenant_scope("acad-1"):
        recipients = await MongoAudienceResolver(db).resolve_payment_risk_audience(
            PaymentRiskAudience(min_days_overdue=7)
        )

    assert [recipient.user_id for recipient in recipients] == ["parent-open"]
    assert recipients[0].email == "open@example.com"


# --------------------------------------------------------------------------- session audience
#
# People CRM engineering spec, section 3.2 "Session campaigns (fix)": the
# session audience used to resolve only enrollments whose status was the
# literal "active", and looked parents up by ``user_id`` only. It now follows
# ROSTER_VISIBLE (the roster's own definition of "in this class") and resolves
# parents alias-aware (``user_id`` or ``auth_uid``), like every other audience.


def test_session_audience_statuses_mirror_roster_visible() -> None:
    """Communications cannot import contexts.enrollment (Rule 5, no
    cross-context imports), so the resolver carries its own copy of the set.
    This is the thing that notices when the two stop agreeing."""
    assert SESSION_AUDIENCE_ENROLLMENT_STATUSES == ROSTER_VISIBLE


async def _seed_session(db, enrollments: list[tuple[str, str]]) -> None:
    """Seed one student + parent per (suffix, status) enrollment in sess-1."""
    await db["enrollments"].insert_many(
        [
            {
                "academy_id": "acad-1",
                "enrollment_id": f"enr-{suffix}",
                "session_id": "sess-1",
                "student_id": f"stu-{suffix}",
                "status": status,
            }
            for suffix, status in enrollments
        ]
    )
    await db["students"].insert_many(
        [
            {"academy_id": "acad-1", "student_id": f"stu-{suffix}", "parent_id": f"par-{suffix}"}
            for suffix, _ in enrollments
        ]
    )
    await db["users"].insert_many(
        [
            {
                "academy_id": "acad-1",
                "user_id": f"par-{suffix}",
                "email": f"{suffix}@example.com",
                "display_name": f"Parent {suffix}",
            }
            for suffix, _ in enrollments
        ]
    )


async def test_session_audience_includes_every_roster_visible_status_and_nothing_else() -> None:
    db = AsyncMongoMockClient()["audience-resolver-session-statuses"]
    statuses = sorted(ENROLLMENT_STATUSES)
    await _seed_session(db, [(status, status) for status in statuses])

    with tenant_scope("acad-1"):
        recipients = await MongoAudienceResolver(db).resolve_session_audience(
            SessionAudience(session_id="sess-1")
        )

    assert sorted(r.user_id for r in recipients) == sorted(
        f"par-{status}" for status in ROSTER_VISIBLE
    )
    # The widening that motivated the fix: a held student's parent hears
    # about their class. Paused and ended enrollments still do not.
    ids = {r.user_id for r in recipients}
    assert "par-held" in ids
    assert "par-paused" not in ids
    assert "par-dropped" not in ids


async def test_session_audience_resolves_parent_linked_by_auth_uid_alias() -> None:
    db = AsyncMongoMockClient()["audience-resolver-session-alias"]
    await db["enrollments"].insert_one(
        {
            "academy_id": "acad-1",
            "enrollment_id": "enr-1",
            "session_id": "sess-1",
            "student_id": "stu-1",
            "status": "active",
        }
    )
    # The student carries the parent's Firebase uid, not their user_id.
    await db["students"].insert_one(
        {"academy_id": "acad-1", "student_id": "stu-1", "parent_id": "firebase-uid-1"}
    )
    await db["users"].insert_one(
        {
            "academy_id": "acad-1",
            "user_id": "parent-1",
            "auth_uid": "firebase-uid-1",
            "email": "alias@example.com",
            "display_name": "Alias Parent",
        }
    )

    with tenant_scope("acad-1"):
        recipients = await MongoAudienceResolver(db).resolve_session_audience(
            SessionAudience(session_id="sess-1")
        )

    assert [(r.user_id, r.email) for r in recipients] == [("parent-1", "alias@example.com")]


async def test_session_audience_dedupes_and_never_reads_another_tenant() -> None:
    db = AsyncMongoMockClient()["audience-resolver-session-tenancy"]
    await db["enrollments"].insert_many(
        [
            # Two siblings in the same class, same parent: one recipient.
            {
                "academy_id": "acad-1",
                "enrollment_id": "enr-1",
                "session_id": "sess-1",
                "student_id": "stu-1",
                "status": "active",
            },
            {
                "academy_id": "acad-1",
                "enrollment_id": "enr-2",
                "session_id": "sess-1",
                "student_id": "stu-2",
                "status": "held",
            },
            # Same session id in another academy: never in this audience.
            {
                "academy_id": "acad-2",
                "enrollment_id": "enr-x",
                "session_id": "sess-1",
                "student_id": "stu-x",
                "status": "active",
            },
        ]
    )
    await db["students"].insert_many(
        [
            {"academy_id": "acad-1", "student_id": "stu-1", "parent_id": "parent-1"},
            {"academy_id": "acad-1", "student_id": "stu-2", "parent_id": "parent-1"},
            {"academy_id": "acad-2", "student_id": "stu-x", "parent_id": "parent-x"},
        ]
    )
    await db["users"].insert_many(
        [
            # A legacy global doc and the tenant-scoped doc for the same
            # parent: the tenant-scoped one wins.
            {"user_id": "parent-1", "email": "global@example.com", "display_name": "Global"},
            {
                "academy_id": "acad-1",
                "user_id": "parent-1",
                "email": "tenant@example.com",
                "display_name": "Tenant",
            },
            # Another academy's copy of the same user id is never read.
            {
                "academy_id": "acad-2",
                "user_id": "parent-1",
                "email": "other-tenant@example.com",
                "display_name": "Other",
            },
            {"academy_id": "acad-2", "user_id": "parent-x", "email": "x@example.com"},
        ]
    )

    with tenant_scope("acad-1"):
        recipients = await MongoAudienceResolver(db).resolve_session_audience(
            SessionAudience(session_id="sess-1")
        )

    assert [(r.user_id, r.email) for r in recipients] == [("parent-1", "tenant@example.com")]
