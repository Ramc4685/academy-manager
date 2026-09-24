"""Index the lookups behind the unified family timeline (People CRM spec §5, Phase 5).

``GET /admin/families/{id}/timeline`` asks, for ONE family of ONE academy,
newest first with a limit of 200:

* ``audit_logs`` rows whose ``entity_id`` is the parent, a child or one of
  the children's enrollments (the admin action allowlist). The only
  ``audit_logs`` index was ``(academy_id, created_at)`` (0060), so the lookup
  scanned the academy's whole audit history (login rows included):
  ``audit_logs_academy_entity_created``.
* the parent-change rows (#785) by the family's side, so a child who LEFT the
  family still shows "Moved to family Y": one equality lookup per alias on
  ``old_parent_id`` and on ``new_parent_id``. Both indexes are PARTIAL on
  ``{field: {"$gt": ""}}`` (#878: the planner-usable shape, never ``$type``);
  only parent-change rows carry the fields, so they stay tiny. The lookups
  are sequential equalities, never an ``$or`` across the two fields.
* ``absence_notices``, ``pause_requests`` and ``makeup_requests`` by the
  family's children (``student_id $in``), newest first. The existing indexes
  key them by occurrence, submitter or parent, not by child.

``attendance`` (0070 ``admin_student_attendance_lookup``), ``enrollments``
(0010), ``trial_requests`` (0145, by ``parent_user_id``) and the CRM's own
collections are already indexed for the timeline's reads.

Every index leads with ``academy_id`` (#849) and none is unique. Building
``audit_logs_academy_entity_created`` reads ``audit_logs`` once (the largest
of these; login audit rows included); the others are small. Idempotent:
``create_index`` with the same name and spec is a no-op.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0202_family_timeline_indexes"

#: (collection, name, keys, options). Exposed so the unit test pins the shapes.
INDEXES: list[tuple[str, str, list[tuple[str, int]], dict[str, Any]]] = [
    (
        "audit_logs",
        "audit_logs_academy_entity_created",
        [("academy_id", 1), ("entity_id", 1), ("created_at", -1)],
        {},
    ),
    (
        "audit_logs",
        "audit_logs_academy_old_parent_created",
        [("academy_id", 1), ("old_parent_id", 1), ("created_at", -1)],
        {"partialFilterExpression": {"old_parent_id": {"$gt": ""}}},
    ),
    (
        "audit_logs",
        "audit_logs_academy_new_parent_created",
        [("academy_id", 1), ("new_parent_id", 1), ("created_at", -1)],
        {"partialFilterExpression": {"new_parent_id": {"$gt": ""}}},
    ),
    (
        "absence_notices",
        "absence_notices_academy_student_submitted",
        [("academy_id", 1), ("student_id", 1), ("submitted_at", -1)],
        {},
    ),
    (
        "pause_requests",
        "pause_requests_academy_student_created",
        [("academy_id", 1), ("student_id", 1), ("created_at", -1)],
        {},
    ),
    (
        "makeup_requests",
        "makeup_requests_academy_student_created",
        [("academy_id", 1), ("student_id", 1), ("created_at", -1)],
        {},
    ),
]


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    for collection, name, keys, options in INDEXES:
        await db[collection].create_index(keys, name=name, **options)
