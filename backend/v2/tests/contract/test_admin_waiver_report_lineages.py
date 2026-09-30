"""Admin waiver report against real documents: one row set per live waiver."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.onboarding.application.use_cases.admin_waivers import ListAdminWaivers
from backend.v2.contexts.onboarding.infrastructure.mongo_admin_waiver_repo import (
    MongoAdminWaiverRepository,
)

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def _template(acad: str, template_id: str, **fields) -> dict:
    return {
        "academy_id": acad,
        "waiver_template_id": template_id,
        "name": fields.pop("name", template_id),
        "version": fields.pop("version", "1"),
        "content_hash": fields.pop("content_hash", f"h-{template_id}"),
        "body": "text",
        "effective_from": NOW,
        "status": "active",
        **fields,
    }


async def _seed_students(db, acad: str) -> None:
    ids = ("st-a", "st-b", "st-c")
    await db["students"].insert_many(
        [
            {
                "academy_id": acad,
                "student_id": sid,
                "full_name": sid,
                "parent_id": f"p-{sid}",
                "status": "active",
            }
            for sid in ids
        ]
    )
    await db["enrollments"].insert_many(
        [
            {
                "academy_id": acad,
                "enrollment_id": f"enr-{sid}",
                "student_id": sid,
                "session_id": session,
                "status": "active",
            }
            for sid, session in (("st-a", "s-jr"), ("st-b", "s-adult"), ("st-c", "s-adult"))
        ]
    )
    await db["sessions"].insert_many(
        [
            {"academy_id": acad, "session_id": "s-jr", "program_id": "prog-juniors"},
            {"academy_id": acad, "session_id": "s-adult", "program_id": "prog-adults"},
        ]
    )


def _signature(acad: str, sig_id: str, sid: str, template_id: str, digest: str) -> dict:
    return {
        "academy_id": acad,
        "waiver_signature_id": sig_id,
        "waiver_template_id": template_id,
        "student_id": sid,
        "parent_user_id": f"p-{sid}",
        "signed_at": NOW - timedelta(days=1),
        "content_hash": digest,
    }


@pytest.mark.asyncio
async def test_blno_shape_one_all_family_waiver_counts_every_student(db, acad) -> None:
    """A single legacy all-family waiver reads as the old single-waiver report."""
    await _seed_students(db, acad)
    await db["waiver_templates"].insert_many(
        [
            _template(
                acad,
                "wt-old",
                version="1",
                status="superseded",
                effective_from=NOW - timedelta(days=90),
                content_hash="h-old",
            ),
            _template(acad, "wt-live", version="2", assigned_to_registration=True),
        ]
    )
    await db["waiver_signatures"].insert_many(
        [
            _signature(acad, "ws-a", "st-a", "wt-live", "h-wt-live"),
            _signature(acad, "ws-b", "st-b", "wt-old", "h-old"),
        ]
    )

    report = await ListAdminWaivers(MongoAdminWaiverRepository(db)).execute()

    assert len(report.lineages) == 1
    assert report.active_waiver is not None and report.active_waiver.waiver_id == "wt-live"
    assert report.summary.total_students == 3
    assert report.summary.current_count == 1
    assert report.summary.outdated_count == 1
    assert report.summary.pending_count == 1
    assert {row.student_id: row.status for row in report.rows} == {
        "st-a": "current",
        "st-b": "outdated",
        "st-c": "pending",
    }


@pytest.mark.asyncio
async def test_two_live_waivers_are_counted_separately(db, acad) -> None:
    await _seed_students(db, acad)
    await db["waiver_templates"].insert_many(
        [
            _template(acad, "wt-liab", lineage_key="liab", required=True, scope="all"),
            _template(
                acad,
                "wt-photo",
                lineage_key="photo",
                required=True,
                scope="programs",
                program_ids=["prog-juniors"],
            ),
            _template(acad, "wt-draft", lineage_key="draft", status="draft", version=None),
        ]
    )
    await db["waiver_signatures"].insert_many(
        [
            _signature(acad, "ws-1", "st-a", "wt-liab", "h-wt-liab"),
            _signature(acad, "ws-2", "st-a", "wt-photo", "h-wt-photo"),
            _signature(acad, "ws-3", "st-b", "wt-liab", "h-wt-liab"),
        ]
    )

    report = await ListAdminWaivers(MongoAdminWaiverRepository(db)).execute()

    by_key = {lineage.waiver.lineage_key: lineage for lineage in report.lineages}
    assert set(by_key) == {"liab", "photo"}
    assert by_key["liab"].summary.total_students == 3
    assert by_key["liab"].summary.current_count == 2
    assert by_key["liab"].summary.pending_count == 1
    # Photo consent applies only to the Juniors program (st-a).
    assert [row.student_id for row in by_key["photo"].rows] == ["st-a"]
    assert by_key["photo"].summary.current_count == 1
    assert {w.waiver_id for w in report.live_waivers} == {"wt-liab", "wt-photo"}


@pytest.mark.asyncio
async def test_other_tenant_waivers_and_signatures_do_not_leak(db, acad) -> None:
    await _seed_students(db, acad)
    await db["waiver_templates"].insert_many(
        [
            _template(acad, "wt-mine", lineage_key="mine", required=True),
            _template("other-academy", "wt-theirs", lineage_key="theirs", required=True),
        ]
    )
    await db["waiver_signatures"].insert_one(
        _signature("other-academy", "ws-x", "st-a", "wt-mine", "h-wt-mine")
    )

    report = await ListAdminWaivers(MongoAdminWaiverRepository(db)).execute()

    assert [lineage.waiver.lineage_key for lineage in report.lineages] == ["mine"]
    assert report.summary.current_count == 0
    assert report.summary.pending_count == 3


@pytest.mark.asyncio
async def test_active_template_never_flagged_required_still_counts_every_student(db, acad) -> None:
    """A BLNO-shaped academy whose template carries no required flag."""
    await _seed_students(db, acad)
    await db["waiver_templates"].insert_one(_template(acad, "wt-plain"))
    await db["waiver_signatures"].insert_one(
        _signature(acad, "ws-a", "st-a", "wt-plain", "h-wt-plain")
    )

    report = await ListAdminWaivers(MongoAdminWaiverRepository(db)).execute()

    assert report.summary.total_students == 3
    assert report.summary.current_count == 1
    assert report.summary.pending_count == 2
    assert report.active_waiver is not None and report.active_waiver.waiver_id == "wt-plain"


@pytest.mark.asyncio
async def test_draft_only_academy_keeps_its_newest_template_as_active_waiver(db, acad) -> None:
    await _seed_students(db, acad)
    await db["waiver_templates"].insert_one(
        _template(acad, "wt-draft", status="draft", version=None)
    )

    data = await MongoAdminWaiverRepository(db).load_admin_waiver_data()
    report = await ListAdminWaivers(MongoAdminWaiverRepository(db)).execute()

    assert data.live_waivers == []
    assert data.active_waiver is not None and data.active_waiver.waiver_id == "wt-draft"
    assert report.summary.total_students == 3
    assert report.summary.pending_count == 3


@pytest.mark.asyncio
async def test_a_different_lineage_is_a_different_waiver_not_an_outdated_signature(
    db, acad
) -> None:
    """New versions inherit their lineage; a fresh lineage key is a new waiver.

    Signing "Old" never reads as signing (or being outdated on) "New".
    """
    await _seed_students(db, acad)
    await db["waiver_templates"].insert_many(
        [
            _template(acad, "wt-old", lineage_key="old", status="superseded", required=True),
            _template(acad, "wt-new", lineage_key="new", required=True),
        ]
    )
    await db["waiver_signatures"].insert_one(_signature(acad, "ws-a", "st-a", "wt-old", "h-wt-old"))

    report = await ListAdminWaivers(MongoAdminWaiverRepository(db)).execute()

    assert [lineage.waiver.lineage_key for lineage in report.lineages] == ["new"]
    assert report.summary.pending_count == 3
    assert report.summary.outdated_count == 0
