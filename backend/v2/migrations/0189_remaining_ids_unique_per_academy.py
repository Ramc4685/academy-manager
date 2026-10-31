"""Scope the remaining id uniqueness to the tenant (issue #849, batch 3).

Thirty single-field unique indexes on a BARE id, from migrations 0040 to
0148, made each id globally unique across every academy while every reader
and writer of those collections is tenant-scoped — the #610 trap, fixed for
``students`` by 0162, the enrollment core by 0186 and billing by 0187. Each
repository was read before this was written: all writes and all id lookups go
through ``TenantScopedRepository`` or carry ``academy_id`` explicitly, with
the one exception handled below.

Each index is replaced with a unique partial index on ``(academy_id, <id>)``
filtered on ``{"<id>": {"$gt": ""}}``. That filter, unlike ``$type:
"string"``, is one the planner will use for equality and ``$in`` lookups (see
0188); by type bracketing it covers strings only, so absent, ``null`` and
``""`` ids stay outside the constraint. The old indexes came in three shapes
(``sparse``, ``$type`` partial, plain); the replacement is uniform.

Digest sends: ``mark_sent`` / ``mark_failed`` / ``mark_skipped_empty`` on
``coach_digest_sends`` and ``parent_digest_sends`` update by ``digest_id``
alone, with no ``academy_id``. A compound index led by ``academy_id`` cannot
serve that, so those two collections also get a plain non-unique
``digest_id`` index. It has the same key as the old unique index, which
MongoDB will not allow side by side, so there it is: create the per-academy
unique index, drop the old global one, create the plain one. Uniqueness is
never absent; the by-``digest_id`` update is unindexed only between two
consecutive commands.

Deliberately NOT touched: ``message_deliveries.provider_message_id``. The
email provider issues it, nothing reads it, and provider ids are global by
construction.

Safety: every collection is pre-flighted BEFORE any index is touched, so one
dirty collection aborts the whole batch with the offenders named. Per index
the new one is created before the old one is dropped. Re-running is a no-op.

Verified against production on 2026-09-21: all thirty global indexes present,
zero duplicate ``(academy_id, <id>)`` pairs, zero docs without a string
``academy_id``.
"""

from __future__ import annotations

import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0189_remaining_ids_unique_per_academy"

log = logging.getLogger(__name__)

#: (collection, id field, old global index, new per-academy index)
TARGETS: list[tuple[str, str, str, str]] = [
    # registration / ops
    (
        "onboarding_applications",
        "application_id",
        "application_id_unique",
        "application_id_per_academy_uq",
    ),
    ("waitlist", "waitlist_id", "waitlist_id_unique", "waitlist_id_per_academy_uq"),
    ("expenses", "expense_id", "expense_id_unique", "expense_id_per_academy_uq"),
    ("payouts", "payout_id", "payout_id_unique", "payout_id_per_academy_uq"),
    ("enrollment_events", "event_id", "event_id_unique", "event_id_per_academy_uq"),
    (
        "session_types",
        "session_type_id",
        "session_types_id_unique",
        "session_types_id_per_academy_uq",
    ),
    (
        "session_feedback",
        "feedback_id",
        "session_feedback_id_unique",
        "session_feedback_id_per_academy_uq",
    ),
    (
        "academy_settings",
        "settings_id",
        "academy_settings_id_unique",
        "academy_settings_id_per_academy_uq",
    ),
    ("autopay_consents", "consent_id", "consent_id_unique", "consent_id_per_academy_uq"),
    # communications / waivers
    ("messages", "message_id", "message_id_unique", "message_id_per_academy_uq"),
    (
        "message_campaigns",
        "campaign_id",
        "message_campaigns_campaign_id_unique",
        "message_campaigns_campaign_id_per_academy_uq",
    ),
    (
        "message_deliveries",
        "delivery_id",
        "message_deliveries_delivery_id_unique",
        "message_deliveries_delivery_id_per_academy_uq",
    ),
    (
        "coach_digest_sends",
        "digest_id",
        "coach_digest_send_id_unique",
        "coach_digest_send_id_per_academy_uq",
    ),
    (
        "parent_digest_sends",
        "digest_id",
        "parent_digest_send_id_unique",
        "parent_digest_send_id_per_academy_uq",
    ),
    (
        "waiver_templates",
        "waiver_template_id",
        "waiver_template_id_unique",
        "waiver_template_id_per_academy_uq",
    ),
    (
        "waiver_signatures",
        "waiver_signature_id",
        "waiver_signature_id_unique",
        "waiver_signature_id_per_academy_uq",
    ),
    # skill / curriculum catalog
    ("skill_programs", "program_id", "program_id_unique", "program_id_per_academy_uq"),
    ("skill_levels", "level_id", "level_id_unique", "level_id_per_academy_uq"),
    ("skills", "skill_id", "skill_id_unique", "skill_id_per_academy_uq"),
    ("skill_criteria", "criterion_id", "criterion_id_unique", "criterion_id_per_academy_uq"),
    ("external_lesson_refs", "ref_id", "ref_id_unique", "ref_id_per_academy_uq"),
    ("lesson_cards", "card_id", "lesson_card_id_unique", "lesson_card_id_per_academy_uq"),
    (
        "curriculum_video_refs",
        "ref_id",
        "curriculum_video_ref_id_unique",
        "curriculum_video_ref_id_per_academy_uq",
    ),
    # student progress / certificates
    (
        "student_level_progress",
        "progress_id",
        "level_progress_id_unique",
        "level_progress_id_per_academy_uq",
    ),
    (
        "student_skill_progress",
        "skill_progress_id",
        "skill_progress_id_unique",
        "skill_progress_id_per_academy_uq",
    ),
    ("test_attempts", "attempt_id", "attempt_id_unique", "attempt_id_per_academy_uq"),
    ("level_up_recommendations", "rec_id", "rec_id_unique", "rec_id_per_academy_uq"),
    ("skill_certificates", "cert_id", "cert_id_unique", "cert_id_per_academy_uq"),
    ("skill_certificates", "cert_number", "cert_number_unique", "cert_number_per_academy_uq"),
    ("coach_skill_notes", "note_id", "skill_note_id_unique", "skill_note_id_per_academy_uq"),
]

#: Collections whose id is also updated by the BARE id (no ``academy_id``), so
#: they keep a plain single-field index: collection -> (field, index name).
PLAIN_LOOKUPS: dict[str, tuple[str, str]] = {
    "coach_digest_sends": ("digest_id", "coach_digest_send_id_lookup"),
    "parent_digest_sends": ("digest_id", "parent_digest_send_id_lookup"),
}


async def _duplicate_pairs(collection, field: str) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    """(academy_id, <id>) pairs that would break the new index."""
    cursor = collection.aggregate(
        [
            {"$match": {field: {"$gt": ""}}},
            {
                "$group": {
                    "_id": {"academy_id": "$academy_id", "id": f"${field}"},
                    "count": {"$sum": 1},
                }
            },
            {"$match": {"count": {"$gt": 1}}},
            {"$limit": 20},
        ]
    )
    return [doc async for doc in cursor]


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    # Pre-flight every collection before touching a live constraint, so a
    # failure is a readable message and the batch is all-or-nothing.
    problems: list[str] = []
    for collection, field, _old_index, new_index in TARGETS:
        duplicates = await _duplicate_pairs(db[collection], field)
        if duplicates:
            offenders = ", ".join(
                f"{row['_id'].get('academy_id')!r}/{row['_id'].get('id')!r} x{row['count']}"
                for row in duplicates
            )
            problems.append(
                f"{collection} has duplicate (academy_id, {field}) pairs, so "
                f"{new_index} cannot be created (up to 20 shown): {offenders}"
            )
    if problems:
        raise RuntimeError(
            "0189 aborted before changing any index. Deduplicate these first: "
            + "; ".join(problems)
            + ". The old global indexes have been left in place."
        )

    for collection, field, old_index, new_index in TARGETS:
        coll = db[collection]
        # Create first, drop second: uniqueness is never absent in between.
        await coll.create_index(
            [("academy_id", 1), (field, 1)],
            unique=True,
            partialFilterExpression={field: {"$gt": ""}},
            name=new_index,
        )
        existing = await coll.index_information()
        if old_index in existing:
            await coll.drop_index(old_index)
            log.info("0189: dropped globally-unique %s in favour of %s", old_index, new_index)
        plain = PLAIN_LOOKUPS.get(collection)
        if plain is not None and plain[0] == field:
            # Same key as the index just dropped, so it can only follow it.
            await coll.create_index(field, name=plain[1])
