"""Mongo audience resolver membership lookups."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.v2.contexts.communications.domain.models import AcademyAudience, PaymentRiskAudience
from backend.v2.contexts.communications.infrastructure.mongo_audience_resolver import (
    MongoAudienceResolver,
)
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
