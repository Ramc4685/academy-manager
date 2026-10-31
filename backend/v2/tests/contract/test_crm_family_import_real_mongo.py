"""CSV family import (roadmap L8a) on a real ``mongod``.

``real_db`` replays every migration (0199 included), so the batch store,
the student writes and the duplicate finder's lookups run against the
production indexes and the ``students`` validator. Wired exactly as
``composition/family_import.py`` wires it. Checks:

* a preview writes no student, only the batch and an audit row;
* a commit writes the planned students, all in the caller's academy, with
  the roster parent fields for a new family; nothing is emailed or provisioned
  (no users document appears);
* committing the same batch again, or twice at once, inserts nothing more;
* re-uploading a committed file previews every row as ``skip`` and commits
  nothing (the new roster family is found by its email AND by phone);
* an existing family matched by email gets the new child, and a child it
  already has is skipped;
* errors (a staff email, a family contact's phone) refuse the commit;
* the commit re-plans: a family added between preview and commit is used;
* a crashed commit (stale claim) is resumed without duplicates;
* another academy is never touched: its same-email family is not matched,
  its admin cannot commit this academy's batch, its students are unchanged.

Synthetic names only. Skipped without a ``mongod``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from backend.v2.composition.family_import import compose_admin_family_import
from backend.v2.contexts.crm.domain.errors import ImportBatchNotFound, ImportNotCommittable
from backend.v2.shared.tenancy import tenant_scope

A = "acad-import-a"
B = "acad-import-b"
TODAY = date(2026, 9, 24)

HEADER = "parent_name,parent_email,parent_phone,student_name,student_date_of_birth\n"
FILE = HEADER + (
    "Nova Testparent,nova.parent@example.test,555-010-4411,Ivy Testkid,2016-05-04\n"
    "Nova Testparent,,+1 (555) 010-4411,Rex Testkid,\n"
    "Orin Testparent,,555-010-5522,Ada Testkid,2015-01-02\n"
)


async def _seed(db: Any) -> None:
    await db["academies"].insert_many(
        [
            {"academy_id": A, "display_name": "Alpha Academy", "timezone": "America/Chicago"},
            {"academy_id": B, "display_name": "Bravo Academy", "timezone": "America/Chicago"},
        ]
    )
    await db["users"].insert_many(
        [
            {
                "user_id": "a-parent",
                "academy_id": A,
                "display_name": "Alpha Testparent",
                "email": "alpha.parent@example.test",
                "normalized_email": "alpha.parent@example.test",
                "roles": ["parent"],
            },
            {
                "user_id": "a-coach",
                "academy_id": A,
                "display_name": "Alpha Testcoach",
                "email": "alpha.coach@example.test",
                "normalized_email": "alpha.coach@example.test",
                "roles": ["coach"],
            },
            {
                "user_id": "b-parent",
                "academy_id": B,
                "display_name": "Bravo Testparent",
                "email": "nova.parent@example.test",  # same email, other academy
                "normalized_email": "nova.parent@example.test",
                "roles": ["parent"],
            },
        ]
    )
    await db["academy_memberships"].insert_many(
        [
            {
                "academy_id": A,
                "membership_id": "m1",
                "user_id": "a-parent",
                "roles": ["parent"],
                "status": "active",
            },
            {
                "academy_id": A,
                "membership_id": "m2",
                "user_id": "a-coach",
                "roles": ["coach"],
                "status": "active",
            },
            {
                "academy_id": B,
                "membership_id": "m3",
                "user_id": "b-parent",
                "roles": ["parent"],
                "status": "active",
            },
        ]
    )
    await db["students"].insert_many(
        [
            {
                "academy_id": A,
                "student_id": "a-kid",
                "parent_id": "a-parent",
                "full_name": "Alpha Kiddo",
            },
            {
                "academy_id": B,
                "student_id": "b-kid",
                "parent_id": "b-parent",
                "full_name": "Ivy Testkid",
            },
        ]
    )
    await db["family_contacts"].insert_one(
        {
            "academy_id": A,
            "contact_id": "a-fc",
            "parent_id": "a-parent",
            "name": "Alpha Secondparent",
            "relationship": "parent",
            "email": "second.alpha@example.test",
            "phone_digits": "5550107070",
            "created_by": "a-admin",
            "created_at": datetime(2026, 9, 1, tzinfo=UTC),
            "updated_at": datetime(2026, 9, 1, tzinfo=UTC),
        }
    )


async def _preview(db: Any, academy: str, csv_text: str, **kw: Any) -> Any:
    services = compose_admin_family_import(db)
    with tenant_scope(academy):
        return await services.preview.execute(
            academy,
            csv_text=csv_text,
            filename="families.csv",
            actor_id=f"{academy}-admin",
            today=TODAY,
            **kw,
        )


async def _commit(db: Any, academy: str, batch_id: str) -> Any:
    services = compose_admin_family_import(db)
    with tenant_scope(academy):
        return await services.commit.execute(
            academy, import_batch_id=batch_id, actor_id=f"{academy}-admin"
        )


async def _students(db: Any, academy: str) -> list[dict[str, Any]]:
    return [
        doc
        async for doc in db["students"]
        .find({"academy_id": academy}, {"_id": 0})
        .sort("full_name", 1)
    ]


async def test_preview_writes_only_the_batch_and_an_audit_row(real_db: Any) -> None:
    await _seed(real_db)
    batch = await _preview(real_db, A, FILE)

    assert [row.status for row in batch.rows] == ["create", "create", "create"]
    assert [row.family_action for row in batch.rows] == ["new", "new", "new"]
    # Rex joins Ivy's family by phone; Orin is a separate new family.
    assert batch.rows[0].family_id == batch.rows[1].family_id != batch.rows[2].family_id
    assert batch.summary.families_new == 2 and batch.summary.rows_create == 3
    assert len(await _students(real_db, A)) == 1  # only the seeded child
    stored = await real_db["import_batches"].find_one({"import_batch_id": batch.import_batch_id})
    assert stored["academy_id"] == A and stored["status"] == "previewed"
    audit = await real_db["audit_logs"].find_one({"entity_id": batch.import_batch_id})
    assert audit["academy_id"] == A and audit["action"] == "crm.import.families.previewed"
    assert "nova" not in repr(audit).lower()  # counts only, no personal data


async def test_commit_writes_roster_families_once(real_db: Any) -> None:
    await _seed(real_db)
    users_before = await real_db["users"].count_documents({})
    batch = await _preview(real_db, A, FILE)

    result = await _commit(real_db, A, batch.import_batch_id)
    assert result.already_committed is False
    assert result.students_inserted == 3
    assert result.batch.status == "committed"

    imported = [s for s in await _students(real_db, A) if s.get("import_batch_id")]
    assert {s["full_name"] for s in imported} == {"Ivy Testkid", "Rex Testkid", "Ada Testkid"}
    ivy = next(s for s in imported if s["full_name"] == "Ivy Testkid")
    rex = next(s for s in imported if s["full_name"] == "Rex Testkid")
    assert ivy["parent_id"] == rex["parent_id"] == batch.rows[0].family_id
    # Family-level parent details on every child, first value wins.
    assert rex["parent_email"] == "nova.parent@example.test"
    assert rex["parent_name"] == "Nova Testparent"
    assert rex["parent_phone"] == "5550104411"
    assert ivy["date_of_birth"] == "2016-05-04"
    assert "date_of_birth" not in rex
    assert all(s["academy_id"] == A for s in imported)
    # No account, no login: nothing written to users.
    assert await real_db["users"].count_documents({}) == users_before
    # Academy B untouched.
    assert [s["student_id"] for s in await _students(real_db, B)] == ["b-kid"]

    again = await _commit(real_db, A, batch.import_batch_id)
    assert again.already_committed is True and again.students_inserted == 0
    assert len(await _students(real_db, A)) == 4
    actions = [
        doc["action"]
        async for doc in real_db["audit_logs"].find({"entity_id": batch.import_batch_id})
    ]
    assert sorted(actions) == ["crm.import.families.committed", "crm.import.families.previewed"]


async def test_reuploading_a_committed_file_is_a_no_op(real_db: Any) -> None:
    await _seed(real_db)
    first = await _preview(real_db, A, FILE)
    await _commit(real_db, A, first.import_batch_id)
    count = len(await _students(real_db, A))

    second = await _preview(real_db, A, FILE)
    assert [row.status for row in second.rows] == ["skip", "skip", "skip"]
    assert [row.family_action for row in second.rows] == ["existing"] * 3
    # Found by email (Nova) and by phone only (Orin had no email).
    assert second.rows[0].family_id == first.rows[0].family_id
    assert second.rows[2].family_id == first.rows[2].family_id
    result = await _commit(real_db, A, second.import_batch_id)
    assert result.students_inserted == 0
    assert len(await _students(real_db, A)) == count


async def test_an_existing_account_family_gets_the_new_child_only(real_db: Any) -> None:
    await _seed(real_db)
    batch = await _preview(
        real_db,
        A,
        HEADER
        + "Alpha Testparent,ALPHA.Parent@example.test,,alpha kiddo,\n"
        + "Alpha Testparent,alpha.parent@example.test,,Beta Kiddo,\n",
    )
    assert [row.status for row in batch.rows] == ["skip", "create"]
    assert {row.family_id for row in batch.rows} == {"a-parent"}
    assert batch.rows[1].family_name == "Alpha Testparent"
    await _commit(real_db, A, batch.import_batch_id)
    beta = await real_db["students"].find_one({"academy_id": A, "full_name": "Beta Kiddo"})
    assert beta["parent_id"] == "a-parent"
    # An existing family keeps its own parent details.
    assert "parent_email" not in beta and "parent_name" not in beta


async def test_staff_email_and_family_contact_phone_are_errors_that_block_commit(
    real_db: Any,
) -> None:
    await _seed(real_db)
    batch = await _preview(
        real_db,
        A,
        HEADER
        + "Coach Parent,alpha.coach@example.test,,Cody Kid,\n"
        + "Second Parent,,+1 555 010 7070,Sid Kid,\n"
        + "Fine Parent,fine@example.test,,Fin Kid,\n",
    )
    assert [row.status for row in batch.rows] == ["error", "error", "create"]
    assert "account" in batch.rows[0].errors[0].message
    assert "contact of an existing family" in batch.rows[1].errors[0].message
    with pytest.raises(ImportNotCommittable) as caught:
        await _commit(real_db, A, batch.import_batch_id)
    assert caught.value.details["reason"] == "has_errors"
    stored = await real_db["import_batches"].find_one({"import_batch_id": batch.import_batch_id})
    assert stored["status"] == "previewed"
    assert await real_db["students"].count_documents({"academy_id": A, "full_name": "Fin Kid"}) == 0


async def test_the_commit_replans_against_current_data(real_db: Any) -> None:
    await _seed(real_db)
    batch = await _preview(real_db, A, HEADER + "Mia Testparent,mia@example.test,,Tia Kid,\n")
    assert batch.rows[0].family_action == "new"
    # Meanwhile someone adds Mia's family by hand.
    await real_db["students"].insert_one(
        {
            "academy_id": A,
            "student_id": "manual-kid",
            "parent_id": "manual-parent",
            "full_name": "Leo Kid",
            "parent_name": "Mia Testparent",
            "parent_email": "mia@example.test",
        }
    )
    result = await _commit(real_db, A, batch.import_batch_id)
    assert result.batch.rows[0].family_action == "existing"
    tia = await real_db["students"].find_one({"academy_id": A, "full_name": "Tia Kid"})
    assert tia["parent_id"] == "manual-parent"


async def test_concurrent_commits_insert_each_student_once(real_db: Any) -> None:
    await _seed(real_db)
    batch = await _preview(real_db, A, FILE)
    outcomes = await asyncio.gather(
        *(_commit(real_db, A, batch.import_batch_id) for _ in range(4)), return_exceptions=True
    )
    finished = [o for o in outcomes if not isinstance(o, BaseException)]
    refused = [o for o in outcomes if isinstance(o, BaseException)]
    assert all(isinstance(o, ImportNotCommittable) for o in refused)
    assert sum(o.students_inserted for o in finished) == 3
    assert (
        await real_db["students"].count_documents({"import_batch_id": batch.import_batch_id}) == 3
    )


async def test_a_crashed_commit_is_resumed_without_duplicates(real_db: Any) -> None:
    await _seed(real_db)
    batch = await _preview(real_db, A, FILE)
    # Simulate a commit that claimed the batch, wrote one student, and died.
    first = batch.rows[0]
    await real_db["students"].insert_one(
        {
            "academy_id": A,
            "student_id": first.student_id,
            "parent_id": first.family_id,
            "full_name": "Ivy Testkid",
            "parent_email": "nova.parent@example.test",
            "import_batch_id": batch.import_batch_id,
        }
    )
    stale = datetime.now(UTC) - timedelta(minutes=10)
    await real_db["import_batches"].update_one(
        {"academy_id": A, "import_batch_id": batch.import_batch_id},
        {"$set": {"status": "committing", "claimed_at": stale}},
    )
    result = await _commit(real_db, A, batch.import_batch_id)
    assert result.batch.status == "committed"
    assert (
        await real_db["students"].count_documents({"import_batch_id": batch.import_batch_id}) == 3
    )


async def test_a_fresh_claim_is_not_stolen(real_db: Any) -> None:
    await _seed(real_db)
    batch = await _preview(real_db, A, FILE)
    await real_db["import_batches"].update_one(
        {"academy_id": A, "import_batch_id": batch.import_batch_id},
        {"$set": {"status": "committing", "claimed_at": datetime.now(UTC)}},
    )
    with pytest.raises(ImportNotCommittable) as caught:
        await _commit(real_db, A, batch.import_batch_id)
    assert caught.value.details["reason"] == "in_progress"


async def test_an_expired_preview_cannot_be_committed(real_db: Any) -> None:
    await _seed(real_db)
    batch = await _preview(real_db, A, FILE)
    await real_db["import_batches"].update_one(
        {"academy_id": A, "import_batch_id": batch.import_batch_id},
        {"$set": {"created_at": datetime.now(UTC) - timedelta(days=2)}},
    )
    with pytest.raises(ImportNotCommittable) as caught:
        await _commit(real_db, A, batch.import_batch_id)
    assert caught.value.details["reason"] == "expired"


async def test_another_academy_is_never_matched_nor_able_to_commit(real_db: Any) -> None:
    await _seed(real_db)
    batch = await _preview(real_db, A, FILE)
    # B's parent shares Nova's email and B has an "Ivy Testkid": A never sees them.
    assert batch.rows[0].family_action == "new"
    assert batch.rows[0].status == "create"
    with pytest.raises(ImportBatchNotFound):
        await _commit(real_db, B, batch.import_batch_id)
    assert (
        await real_db["students"].count_documents({"import_batch_id": batch.import_batch_id}) == 0
    )
    await _commit(real_db, A, batch.import_batch_id)
    assert [s["student_id"] for s in await _students(real_db, B)] == ["b-kid"]
    assert (
        await real_db["students"].count_documents(
            {"import_batch_id": batch.import_batch_id, "academy_id": {"$ne": A}}
        )
        == 0
    )


async def test_the_commit_refuses_a_batch_of_another_academy_even_if_the_store_finds_it(
    real_db: Any,
) -> None:
    # Belt and braces over the store's tenant scoping: the context says A (so
    # the store reads A's batch) but the caller commits for B.
    await _seed(real_db)
    batch = await _preview(real_db, A, FILE)
    assert batch.academy_id == A
    services = compose_admin_family_import(real_db)
    with tenant_scope(A), pytest.raises(ImportBatchNotFound):
        await services.commit.execute(B, import_batch_id=batch.import_batch_id, actor_id="b-admin")
    stored = await real_db["import_batches"].find_one({"import_batch_id": batch.import_batch_id})
    assert stored["status"] == "previewed"
    assert (
        await real_db["students"].count_documents({"import_batch_id": batch.import_batch_id}) == 0
    )


async def test_the_batch_lookup_is_served_by_its_index(real_db: Any) -> None:
    await _seed(real_db)
    batch = await _preview(real_db, A, FILE)
    plan = (
        await real_db["import_batches"]
        .find({"academy_id": A, "import_batch_id": batch.import_batch_id})
        .explain()
    )
    assert "import_batches_academy_batch_unique" in repr(plan["queryPlanner"]["winningPlan"])
