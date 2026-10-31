"""Family Messages sources and the contact log on a real ``mongod`` (0203 applied).

Checks: each send-log source reads only this family's rows of this academy
(the same ids in another academy never show; a digest that was never sent is
left out; the staff absence alert is not a family message; another family's
contact with the same email never shows); the contact log repository stamps
the tenant, completes a pending handoff exactly once under concurrency, and
its reads are served by the 0203 index. Skipped without a ``mongod``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.crm.application.family_messages import (
    CompleteFamilyContactLog,
    FamilyMessagesScope,
    LogFamilyContact,
)
from backend.v2.contexts.crm.application.use_cases.family_notes import Actor
from backend.v2.contexts.crm.domain.errors import DuplicateCrmRecordId
from backend.v2.contexts.crm.domain.family_messages import FamilyContactLog
from backend.v2.contexts.crm.infrastructure.family_message_sources import (
    AbsenceNoticeSendsSource,
    CampaignDeliveriesSource,
    ContactLogSource,
    InvoiceContactCopiesSource,
    ParentDigestSource,
)
from backend.v2.contexts.crm.infrastructure.mongo_family_contact_log_repo import (
    MongoFamilyContactLogRepository,
)
from backend.v2.contexts.crm.infrastructure.mongo_family_contacts_repo import (
    MongoFamilyContactRepository,
)
from backend.v2.shared.tenancy import tenant_scope
from backend.v2.tests.unit.test_crm_family_messages import Directory

A = "acad-a"  # Directory() in the unit test knows p-1 in this academy
B = "acad-msg-b"
T0 = datetime(2026, 9, 1, 15, 0, tzinfo=UTC)


def _scope(academy_id: str = A) -> FamilyMessagesScope:
    return FamilyMessagesScope(
        academy_id=academy_id,
        family_id="p-1",
        parent_aliases=("p-1", "fb-p-1"),
        student_ids=("s-1",),
        student_names={"s-1": "Kid Alpha"},
    )


async def test_campaign_deliveries_by_alias_with_subject(real_db: Any) -> None:
    await real_db["message_campaigns"].insert_many(
        [
            {
                "academy_id": A,
                "campaign_id": "c-1",
                "subject": "Holiday schedule",
                "created_at": T0,
            },
            {"academy_id": B, "campaign_id": "c-1", "subject": "Other academy", "created_at": T0},
        ]
    )
    await real_db["message_deliveries"].insert_many(
        [
            {
                "academy_id": A,
                "delivery_id": "d-1",
                "campaign_id": "c-1",
                "recipient_user_id": "fb-p-1",
                "recipient_email": "parent@example.test",
                "status": "sent",
                "sent_at": T0 + timedelta(minutes=1),
            },
            {
                "academy_id": A,
                "delivery_id": "d-2",
                "campaign_id": "c-1",
                "recipient_user_id": "p-1",
                "status": "failed",
                "sent_at": None,
                "failed_reason": "bounced",
            },
            # another family, and the same parent id in another academy
            {
                "academy_id": A,
                "delivery_id": "d-3",
                "campaign_id": "c-1",
                "recipient_user_id": "p-9",
            },
            {
                "academy_id": B,
                "delivery_id": "d-4",
                "campaign_id": "c-1",
                "recipient_user_id": "p-1",
                "status": "sent",
                "sent_at": T0,
            },
        ]
    )
    entries = {e.entry_id: e for e in await CampaignDeliveriesSource(real_db).fetch(_scope())}
    assert set(entries) == {"campaign:d-1", "campaign:d-2"}
    assert entries["campaign:d-1"].summary == "Email: Holiday schedule"
    assert entries["campaign:d-1"].recipient == "parent@example.test"
    assert entries["campaign:d-2"].status == "failed"
    assert entries["campaign:d-2"].failed_reason == "bounced"
    assert entries["campaign:d-2"].at == T0  # queued/failed: dated by the campaign


async def test_parent_digest_leaves_out_empty_digests(real_db: Any) -> None:
    await real_db["parent_digest_sends"].insert_many(
        [
            {
                "academy_id": A,
                "digest_id": "g-1",
                "parent_id": "p-1",
                "digest_date": "2026-09-01",
                "status": "sent",
                "sent_at": (T0 + timedelta(hours=1)).isoformat(),  # stored as a string
                "created_at": T0,
            },
            {
                "academy_id": A,
                "digest_id": "g-2",
                "parent_id": "fb-p-1",
                "digest_date": "2026-09-02",
                "status": "skipped_empty",
                "created_at": T0,
            },
            {
                "academy_id": B,
                "digest_id": "g-3",
                "parent_id": "p-1",
                "digest_date": "2026-09-01",
                "status": "sent",
                "created_at": T0,
            },
        ]
    )
    entries = list(await ParentDigestSource(real_db).fetch(_scope()))
    assert [e.entry_id for e in entries] == ["digest:g-1"]
    assert entries[0].summary == "Parent digest for 2026-09-01"
    assert entries[0].at == T0 + timedelta(hours=1)


async def test_absence_notice_confirmation_to_the_parent_only(real_db: Any) -> None:
    await real_db["absence_notices"].insert_many(
        [
            {"academy_id": A, "notice_id": "n-1", "student_id": "s-1", "submitted_at": T0},
            {"academy_id": A, "notice_id": "n-9", "student_id": "s-9", "submitted_at": T0},
            {"academy_id": B, "notice_id": "n-1", "student_id": "s-1", "submitted_at": T0},
        ]
    )
    base = {"status": "sent", "created_at": T0}
    await real_db["absence_notice_sends"].insert_many(
        [
            {"academy_id": A, "send_id": "x-1", "notice_id": "n-1", "audience": "parent", **base},
            {"academy_id": A, "send_id": "x-2", "notice_id": "n-1", "audience": "staff", **base},
            {"academy_id": A, "send_id": "x-3", "notice_id": "n-9", "audience": "parent", **base},
            {"academy_id": B, "send_id": "x-4", "notice_id": "n-1", "audience": "parent", **base},
        ]
    )
    entries = list(await AbsenceNoticeSendsSource(real_db).fetch(_scope()))
    assert [e.entry_id for e in entries] == ["absence_notice:x-1"]
    assert entries[0].summary == "Absence notice confirmation for Kid Alpha"


async def test_invoice_copies_match_the_familys_own_contacts(real_db: Any) -> None:
    contact = {
        "relationship": "parent",
        "created_by": "u-1",
        "created_at": T0,
        "updated_at": T0,
        "gets_invoices": True,
    }
    await real_db["family_contacts"].insert_many(
        [
            {
                "academy_id": A,
                "contact_id": "fc-1",
                "parent_id": "p-1",
                "name": "Second Parent",
                "email": "shared@example.test",
                **contact,
            },
            # another family's contact with the SAME address
            {
                "academy_id": A,
                "contact_id": "fc-2",
                "parent_id": "p-2",
                "name": "Other Family",
                "email": "shared@example.test",
                **contact,
            },
        ]
    )
    base = {"academy_id": A, "recipient_email": "shared@example.test", "status": "sent"}
    await real_db["invoice_contact_email_sends"].insert_many(
        [
            {
                **base,
                "send_id": "ic-1",
                "contact_id": "fc-1",
                "digest_date": "invoice:i-1",
                "created_at": T0,
            },
            {
                **base,
                "send_id": "ic-2",
                "contact_id": "fc-2",
                "digest_date": "invoice:i-2",
                "created_at": T0,
            },
            {
                **base,
                "academy_id": B,
                "send_id": "ic-3",
                "contact_id": "fc-1",
                "digest_date": "invoice:i-1",
                "created_at": T0,
            },
        ]
    )
    with tenant_scope(A):
        source = InvoiceContactCopiesSource(real_db, MongoFamilyContactRepository(real_db))
        entries = list(await source.fetch(_scope()))
    assert [e.entry_id for e in entries] == ["invoice_copy:ic-1"]
    assert entries[0].summary == "Invoice copy to Second Parent"
    assert "$" not in entries[0].summary


def _row(log_id: str, **kw: Any) -> FamilyContactLog:
    base: dict[str, Any] = {
        "log_id": log_id,
        "academy_id": "forged",  # the repository stamps the tenant
        "parent_id": "p-1",
        "channel": "sms",
        "status": "not_logged",
        "note": "hi",
        "author_user_id": "u-1",
        "created_at": T0,
        "updated_at": T0,
    }
    base.update(kw)
    return FamilyContactLog(**base)


async def test_contact_log_is_tenant_stamped_and_scoped(real_db: Any) -> None:
    repo = MongoFamilyContactLogRepository(real_db)
    with tenant_scope(A):
        await repo.add(_row("l-1"))
        with pytest.raises(DuplicateCrmRecordId):
            await repo.add(_row("l-1"))
    with tenant_scope(B):
        await repo.add(_row("l-1"))  # same id in another academy is fine
        assert [r.academy_id for r in await repo.list_for_family("p-1")] == [B]
    stored = await real_db["family_contact_log"].find_one({"academy_id": A, "log_id": "l-1"})
    assert stored is not None
    with tenant_scope(A):
        assert await repo.get("p-2", "l-1") is None  # another family
        entries = list(await ContactLogSource(repo).fetch(_scope()))
    assert [e.entry_id for e in entries] == ["log:l-1"]
    assert entries[0].status == "not_logged"


async def test_concurrent_completes_write_once(real_db: Any) -> None:
    repo = MongoFamilyContactLogRepository(real_db)
    actor = Actor(user_id="u-1", roles=("admin",))
    with tenant_scope(A):
        logged = await LogFamilyContact(repo, Directory(), new_id=lambda: "l-9").execute(
            academy_id=A,
            parent_id="p-1",
            channel="whatsapp",
            status="not_logged",
            note="See you",
            actor=actor,
        )
        assert logged.logged_at is None
        complete = CompleteFamilyContactLog(repo, Directory())
        results = await asyncio.gather(
            *(
                complete.execute(
                    academy_id=A, parent_id="p-1", log_id="l-9", note=None, actor=actor
                )
                for _ in range(5)
            )
        )
    assert {r.status for r in results} == {"logged"}
    assert len({r.logged_at for r in results}) == 1
    doc = await real_db["family_contact_log"].find_one({"academy_id": A, "log_id": "l-9"})
    assert doc is not None and doc["status"] == "logged" and doc["note"] == "See you"


def _index_names(plan: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    if plan.get("indexName"):
        found.add(plan["indexName"])
    for key in ("inputStage", "queryPlan"):
        if isinstance(plan.get(key), dict):
            found |= _index_names(plan[key])
    for child in plan.get("inputStages", []) or []:
        found |= _index_names(child)
    return found


@pytest.mark.parametrize(
    ("collection", "filter_", "sort", "index"),
    [
        (
            "family_contact_log",
            {"academy_id": A, "parent_id": "p-1"},
            {"created_at": -1},
            "family_contact_log_academy_parent_created",
        ),
        (
            "family_contact_log",
            {"academy_id": A, "log_id": "l-1", "parent_id": "p-1"},
            None,
            "family_contact_log_academy_log_id_unique",
        ),
        (
            "message_deliveries",
            {"academy_id": A, "recipient_user_id": "p-1"},
            {"sent_at": -1},
            "message_deliveries_academy_recipient_sent",
        ),
        (
            "invoice_contact_email_sends",
            {"academy_id": A, "recipient_email": "x@example.test", "contact_id": {"$in": ["fc-1"]}},
            {"created_at": -1},
            "invoice_contact_email_sends_key_unique",
        ),
    ],
)
async def test_message_lookups_use_their_indexes(
    real_db: Any, collection: str, filter_: dict[str, Any], sort: dict[str, int] | None, index: str
) -> None:
    command: dict[str, Any] = {"find": collection, "filter": filter_}
    if sort:
        command["sort"] = sort
    explained = await real_db.command("explain", command, verbosity="queryPlanner")
    assert index in _index_names(explained["queryPlanner"]["winningPlan"])
