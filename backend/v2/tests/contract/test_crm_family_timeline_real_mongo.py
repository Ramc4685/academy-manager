"""Family timeline Mongo sources on a real ``mongod`` (migration 0202 applied).

Checks: the admin audit source shows only allowlisted actions (never a
login), keys on the parent, the children and their enrollments, and builds
"Moved from / moved to family" entries from parent-change rows on BOTH
families; the requests and attendance sources read the family's children;
nothing of another academy comes back even with the same ids; and the
timeline lookups are served by their 0202 indexes. Skipped without a
``mongod``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.crm.application.timeline import FamilyTimelineScope
from backend.v2.contexts.crm.infrastructure.family_timeline_sources import (
    AdminAuditTimelineSource,
    AttendanceTimelineSource,
    RequestsTimelineSource,
)

A = "acad-tl-a"
B = "acad-tl-b"
T0 = datetime(2026, 9, 1, 15, 0, tzinfo=UTC)


def _scope(family_id: str, *students: str, academy_id: str = A) -> FamilyTimelineScope:
    names = {"s-1": "Kid Alpha", "s-2": "Kid Beta", "s-3": "Kid Gamma"}
    return FamilyTimelineScope(
        academy_id=academy_id,
        family_id=family_id,
        parent_aliases=(family_id, f"fb-{family_id}"),
        student_ids=students,
        student_names={s: names[s] for s in students},
        family_names={"p-1": "Testparent One", "p-2": "Testparent Two"},
    )


async def _seed_audit(db: Any) -> None:
    rows = [
        # parent profile edit (allowlisted), keyed on the parent's alias
        {
            "action": "user.edited",
            "entity_type": "user",
            "entity_id": "fb-p-1",
            "changed_keys": ["phone"],
            "min": 1,
        },
        # a login: never shown
        {"action": "user_logged_in", "entity_type": "user", "entity_id": "p-1", "min": 2},
        # child profile edit
        {
            "action": "student.edited",
            "entity_type": "student",
            "entity_id": "s-1",
            "changed_keys": ["date_of_birth"],
            "min": 3,
        },
        # stripe reconcile on the child's enrollment
        {
            "action": "billing.stripe_reconcile",
            "entity_type": "enrollment",
            "entity_id": "enr-1",
            "min": 4,
        },
        # s-3 moved from p-1 to p-2
        {
            "action": "student.parent_changed",
            "entity_type": "student",
            "entity_id": "s-3",
            "old_parent_id": "p-1",
            "new_parent_id": "p-2",
            "reason": "custody",
            "min": 5,
        },
    ]
    docs = []
    for i, r in enumerate(rows):
        minutes = r.pop("min")
        docs.append(
            {
                "audit_id": f"au-{i}",
                "academy_id": A,
                "actor_id": "u-admin",
                "created_at": T0 + timedelta(minutes=minutes),
                **r,
            }
        )
    # The same ids in another academy: never visible from A.
    docs.append(
        {
            "audit_id": "au-b",
            "academy_id": B,
            "actor_id": "u-b",
            "action": "user.edited",
            "entity_type": "user",
            "entity_id": "p-1",
            "created_at": T0,
        }
    )
    await db["audit_logs"].insert_many(docs)
    await db["enrollments"].insert_many(
        [
            {
                "academy_id": A,
                "enrollment_id": "enr-1",
                "student_id": "s-1",
                "session_id": "ses-1",
                "status": "active",
            },
            {
                "academy_id": B,
                "enrollment_id": "enr-b",
                "student_id": "s-1",
                "session_id": "ses-b",
                "status": "active",
            },
        ]
    )
    await db["students"].insert_one(
        {"academy_id": A, "student_id": "s-3", "full_name": "Kid Gamma", "parent_id": "p-2"}
    )


async def test_admin_audit_allowlist_and_moved_entries(real_db: Any) -> None:
    await _seed_audit(real_db)
    source = AdminAuditTimelineSource(real_db)

    old_family = {e.entry_id: e for e in (await source.fetch(_scope("p-1", "s-1"))).entries}
    assert set(old_family) == {"audit:au-0", "audit:au-2", "audit:au-3", "audit:au-4"}
    assert old_family["audit:au-0"].summary == "Parent profile edited · phone"
    assert old_family["audit:au-2"].summary == "Child profile edited · Kid Alpha · date of birth"
    assert old_family["audit:au-3"].enrollment_id == "enr-1"
    moved_out = old_family["audit:au-4"]
    assert moved_out.code == "audit:moved_out"
    assert moved_out.summary == "Kid Gamma moved to family Testparent Two · custody"

    new_family = (await source.fetch(_scope("p-2", "s-3"))).entries
    (moved_in,) = new_family
    assert moved_in.code == "audit:moved_in"
    assert moved_in.summary == "Kid Gamma moved from family Testparent One · custody"

    other = (await source.fetch(_scope("p-1", "s-1", academy_id=B))).entries
    assert [e.entry_id for e in other] == ["audit:au-b"]


async def test_requests_and_attendance_read_the_familys_children(real_db: Any) -> None:
    await real_db["pause_requests"].insert_many(
        [
            {
                "academy_id": A,
                "pause_request_id": "pr-1",
                "parent_id": "p-1",
                "period": "2026-09",
                "student_id": "s-1",
                "enrollment_id": "enr-1",
                "session_title": "Sat Beginners",
                "status": "approved",
                "created_at": T0,
                "decided_at": T0 + timedelta(hours=2),
                "decided_by": "u-admin",
            },
            {
                "academy_id": B,
                "pause_request_id": "pr-b",
                "parent_id": "p-1",
                "period": "2026-09",
                "enrollment_id": "enr-b",
                "student_id": "s-1",
                "status": "pending",
                "created_at": T0,
            },
        ]
    )
    await real_db["absence_notices"].insert_one(
        {
            "academy_id": A,
            "notice_id": "an-1",
            "student_id": "s-1",
            "occurrence_id": "occ-1",
            "submitted_by": "p-1",
            "submitted_at": T0 - timedelta(days=1),
        }
    )
    await real_db["trial_requests"].insert_one(
        {
            "academy_id": A,
            "request_id": "tr-1",
            "parent_user_id": "fb-p-1",
            "prospective_child_name": "Kid Delta",
            "status": "pending",
            "created_at": T0,
        }
    )
    await real_db["session_occurrences"].insert_many(
        [
            {
                "academy_id": A,
                "occurrence_id": occ,
                "session_id": "ses-1",
                "start_at": T0 - timedelta(hours=hours),
                "end_at": T0 - timedelta(hours=hours - 1),
            }
            for occ, hours in (("occ-1", 5), ("occ-2", 3), ("occ-3", 2))
        ]
    )
    await real_db["sessions"].insert_one({"academy_id": A, "session_id": "ses-1", "title": "Sat"})
    await real_db["attendance"].insert_many(
        [
            {
                "academy_id": A,
                "attendance_id": "at-1",
                "student_id": "s-1",
                "session_id": "ses-1",
                "occurrence_id": "occ-1",
                "status": "absent",
                "marked_at": T0,
            },
            {
                "academy_id": A,
                "attendance_id": "at-2",
                "student_id": "s-1",
                "session_id": "ses-1",
                "occurrence_id": "occ-2",
                "status": "present",
                "previous_status": "absent",
                "marked_at": T0,
                "corrected_at": T0 + timedelta(hours=1),
            },
            {
                "academy_id": A,
                "attendance_id": "at-3",
                "student_id": "s-1",
                "session_id": "ses-1",
                "occurrence_id": "occ-3",
                "status": "present",
                "marked_at": T0,
            },
            {
                "academy_id": B,
                "attendance_id": "at-b",
                "student_id": "s-1",
                "status": "absent",
                "marked_at": T0,
            },
        ]
    )
    scope = _scope("p-1", "s-1")

    requests = {e.entry_id: e for e in (await RequestsTimelineSource(real_db).fetch(scope)).entries}
    assert set(requests) == {
        "pause:pr-1:asked",
        "pause:pr-1:decided",
        "absence_notice:an-1",
        "trial:tr-1:asked",
    }
    assert requests["pause:pr-1:decided"].summary == (
        "Pause request for Kid Alpha · Sat Beginners approved"
    )
    assert requests["pause:pr-1:decided"].enrollment_id == "enr-1"
    assert requests["trial:tr-1:asked"].summary == "Trial class request for Kid Delta sent"

    attendance = {
        e.entry_id: e for e in (await AttendanceTimelineSource(real_db).fetch(scope)).entries
    }
    assert set(attendance) == {"attendance:at-1", "attendance:at-2"}
    assert attendance["attendance:at-1"].summary == "Kid Alpha marked absent · Sat"
    # Dated by the class, not by when it was marked.
    assert attendance["attendance:at-1"].at == T0 - timedelta(hours=5)
    assert attendance["attendance:at-2"].code == "attendance:corrected"


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
    ("collection", "filter_", "index"),
    [
        (
            "audit_logs",
            {"academy_id": A, "entity_id": {"$in": ["p-1", "s-1"]}, "action": {"$in": ["x"]}},
            "audit_logs_academy_entity_created",
        ),
        (
            "audit_logs",
            {"academy_id": A, "old_parent_id": "p-1", "action": "student.parent_changed"},
            "audit_logs_academy_old_parent_created",
        ),
        (
            "audit_logs",
            {"academy_id": A, "new_parent_id": "p-1", "action": "student.parent_changed"},
            "audit_logs_academy_new_parent_created",
        ),
        (
            "pause_requests",
            {"academy_id": A, "student_id": {"$in": ["s-1", "s-2"]}},
            "pause_requests_academy_student_created",
        ),
        (
            "makeup_requests",
            {"academy_id": A, "student_id": {"$in": ["s-1", "s-2"]}},
            "makeup_requests_academy_student_created",
        ),
    ],
)
async def test_timeline_lookups_use_their_indexes(
    real_db: Any, collection: str, filter_: dict[str, Any], index: str
) -> None:
    await _seed_audit(real_db)
    explained = await real_db.command(
        "explain",
        {"find": collection, "filter": filter_, "sort": {"created_at": -1}},
        verbosity="queryPlanner",
    )
    assert index in _index_names(explained["queryPlanner"]["winningPlan"])


async def test_absence_notice_lookup_uses_its_index(real_db: Any) -> None:
    explained = await real_db.command(
        "explain",
        {
            "find": "absence_notices",
            "filter": {"academy_id": A, "student_id": {"$in": ["s-1"]}},
            "sort": {"submitted_at": -1},
        },
        verbosity="queryPlanner",
    )
    names = _index_names(explained["queryPlanner"]["winningPlan"])
    assert "absence_notices_academy_student_submitted" in names
