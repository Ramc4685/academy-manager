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
