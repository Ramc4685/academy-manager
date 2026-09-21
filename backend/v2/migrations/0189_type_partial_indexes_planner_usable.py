"""Make the ``$type``-filtered partial indexes serve lookups (issue #878).

MongoDB's planner cannot prove that an equality or ``$in`` lookup satisfies a
``{"<field>": {"$type": "string"}}`` partial filter, so it never uses such an
index for a read: the index enforces uniqueness and nothing else. Replaying
every migration leaves 34 of them, and no sibling index covers the same field,
so lookups such as the Stripe webhook's ``ledger_idempotency_key`` /
``stripe_payment_intent_id`` / ``stripe_checkout_session_id`` reads, the
checkout webhook's ``onboarding_applications.payment_id`` read and attendance
marking's ``(occurrence_id, student_id)`` read are all collection scans.
Verified with ``explain()`` on MongoDB 7.0.31: 3000 of 3000 documents examined
with ``$type``, 1 key and 1 document with ``$gt: ""`` (#878 has the table).

This rebuilds the 25 that are already led by ``academy_id`` with every
``$type: "string"`` clause turned into ``{"$gt": ""}``; any other clause (the
``status`` list on ``uq_registration_active_student_lock``) is kept. Same key,
same ``unique``. By type bracketing ``$gt: ""`` still covers strings only, so
absent and ``null`` stay out of the constraint as before; ``""`` now stays out
too. The nine ``$type`` indexes keyed on a bare id are #849's to re-key per
academy and are left alone here.

Index NAMES are preserved, because ``launch_readiness_audit.py`` and several
contract tests require them by name. MongoDB cannot rename or alter an index,
so each one is swapped in four steps: build a ``__swap`` twin, drop the
original, rebuild it under the original name, drop the twin. MongoDB refuses
two indexes with an identical spec under different names, so the twin filters
on ``$gte: ""`` instead: still strings only, still a subset of the old filter,
and it only lives for the length of the swap. Uniqueness is enforced by one of
the two at every point, and every step is keyed off ``index_information()``,
so a run that dies half-way resumes.

Safety: ``$gt: ""`` selects a subset of what ``$type: "string"`` selects, and
the old index already guarantees that set is duplicate-free, so no create can
fail on existing data and no pre-flight is needed. Re-running is a no-op.

``get_by_stripe_pi`` also matches the pre-v2 ``stripe_payment_intent`` field.
That branch had no index at all, so ``payments`` and ``ledger_payments`` each
get a small non-unique one; only legacy rows carry the field.
"""

from __future__ import annotations

import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0189_type_partial_indexes_planner_usable"

log = logging.getLogger(__name__)

_STRING = {"$type": "string"}
_PLANNER_USABLE = {"$gt": ""}
_TWIN = {"$gte": ""}
_SWAP_SUFFIX = "__swap"

#: (collection, index name, key fields, unique, partial filter as built today)
TARGETS: list[tuple[str, str, list[str], bool, dict[str, Any]]] = [
    (
        "academy_settings",
        "academy_settings_academy_unique",
        ["academy_id"],
        True,
        {"academy_id": _STRING},
    ),
    (
        "account_credit_ledger",
        "academy_credit_id_unique",
        ["academy_id", "credit_id"],
        True,
        {"credit_id": _STRING},
    ),
    (
        "account_credit_ledger",
        "academy_credit_source_unique",
        ["academy_id", "source_type", "source_id"],
        True,
        {"source_type": _STRING, "source_id": _STRING},
    ),
    (
        "attendance",
        "attendance_occurrence_unique",
        ["academy_id", "occurrence_id", "student_id"],
        True,
        {"occurrence_id": _STRING},
    ),
    (
        "billing_calculation_snapshots",
        "academy_snapshot_unique",
        ["academy_id", "snapshot_id"],
        True,
        {"snapshot_id": _STRING},
    ),
    (
        "coach_attendance",
        "coach_attendance_occurrence_coach_unique",
        ["academy_id", "occurrence_id", "coach_id"],
        True,
        {"occurrence_id": _STRING, "coach_id": _STRING},
    ),
    (
        "enrollments",
        "uq_registration_active_student_lock",
        ["academy_id", "registration_student_lock"],
        True,
        {
            "registration_student_lock": _STRING,
            "status": {"$in": ["active", "held", "paused", "reclaim_pending"]},
        },
    ),
    (
        "invoices",
        "academy_invoice_idempotency_unique",
        ["academy_id", "idempotency_key"],
        True,
        {"idempotency_key": _STRING},
    ),
    (
        "invoices",
        "academy_stripe_invoice_unique",
        ["academy_id", "stripe_invoice_id"],
        True,
        {"stripe_invoice_id": _STRING},
    ),
    (
        "invoices",
        "invoices_academy_invoice_number_unique",
        ["academy_id", "invoice_number"],
        True,
        {"invoice_number": _STRING},
    ),
    (
        "ledger_payments",
        "academy_ledger_payment_checkout_session",
        ["academy_id", "stripe_checkout_session_id"],
        False,
        {"stripe_checkout_session_id": _STRING},
    ),
    (
        "ledger_payments",
        "academy_ledger_payment_id_unique",
        ["academy_id", "payment_id"],
        True,
        {"payment_id": _STRING},
    ),
    (
        "ledger_payments",
        "academy_ledger_payment_idempotency_unique",
        ["academy_id", "ledger_idempotency_key"],
        True,
        {"ledger_idempotency_key": _STRING},
    ),
    (
        "ledger_payments",
        "academy_ledger_payment_intent_unique",
        ["academy_id", "stripe_payment_intent_id"],
        True,
        {"stripe_payment_intent_id": _STRING},
    ),
    (
        "ledger_payments",
        "academy_ledger_payment_stripe_invoice",
        ["academy_id", "stripe_invoice_id"],
        False,
        {"stripe_invoice_id": _STRING},
    ),
    (
        "message_campaigns",
        "message_campaigns_academy_idempotency_key_unique",
        ["academy_id", "idempotency_key"],
        True,
        {"idempotency_key": _STRING},
    ),
    (
        "onboarding_applications",
        "academy_payment_id",
        ["academy_id", "payment_id"],
        False,
        {"payment_id": _STRING},
    ),
    (
        "parent_billing_customers",
        "academy_stripe_customer_unique",
        ["academy_id", "stripe_customer_id"],
        True,
        {"stripe_customer_id": _STRING},
    ),
    (
        "payment_allocations",
        "academy_allocation_idempotency_unique",
        ["academy_id", "idempotency_key"],
        True,
        {"idempotency_key": _STRING},
    ),
    (
        "payment_attempts",
        "academy_payment_attempt_idempotency_unique",
        ["academy_id", "idempotency_key"],
        True,
        {"idempotency_key": _STRING},
    ),
    (
        "payments",
        "academy_calculation_snapshot",
        ["academy_id", "calculation_snapshot_id"],
        False,
        {"calculation_snapshot_id": _STRING},
    ),
    (
        "payments",
        "academy_checkout_session_unique",
        ["academy_id", "stripe_checkout_session_id"],
        True,
        {"stripe_checkout_session_id": _STRING},
    ),
    (
        "payments",
        "academy_stripe_pi_unique",
        ["academy_id", "stripe_payment_intent_id"],
        True,
        {"stripe_payment_intent_id": _STRING},
    ),
    (
        "scheduled_enrollment_actions",
        "unique_pause_action",
        ["academy_id", "pause_request_id", "action_type"],
        True,
        {"pause_request_id": _STRING},
    ),
    (
        "subscriptions",
        "academy_subscription_checkout_session_unique",
        ["academy_id", "stripe_checkout_session_id"],
        True,
        {"stripe_checkout_session_id": _STRING},
    ),
]

#: Collections ``get_by_stripe_pi`` reads by the pre-v2 field name.
LEGACY_PI_COLLECTIONS = ("payments", "ledger_payments")
LEGACY_PI_INDEX = "academy_legacy_stripe_payment_intent"


def _restring(partial: dict[str, Any], replacement: dict[str, Any]) -> dict[str, Any]:
    return {
        field: (dict(replacement) if clause == _STRING else clause)
        for field, clause in partial.items()
    }


def planner_usable(partial: dict[str, Any]) -> dict[str, Any]:
    """The same filter with every ``$type: "string"`` clause made ``$gt: ""``."""
    return _restring(partial, _PLANNER_USABLE)


async def _swap(
    db: AsyncIOMotorDatabase,  # type: ignore[type-arg]
    collection: str,
    name: str,
    fields: list[str],
    unique: bool,
    partial: dict[str, Any],
) -> None:
    coll = db[collection]
    key = [(field, 1) for field in fields]
    wanted = planner_usable(partial)
    swap = name + _SWAP_SUFFIX

    info = await coll.index_information()
    if info.get(name, {}).get("partialFilterExpression") != wanted:
        if swap not in info:
            await coll.create_index(
                key,
                unique=unique,
                partialFilterExpression=_restring(partial, _TWIN),
                name=swap,
            )
        if name in info:
            await coll.drop_index(name)
        await coll.create_index(key, unique=unique, partialFilterExpression=wanted, name=name)
        log.info("0189: rebuilt %s.%s with a planner-usable filter", collection, name)
    if swap in await coll.index_information():
        await coll.drop_index(swap)


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    for collection, name, fields, unique, partial in TARGETS:
        await _swap(db, collection, name, fields, unique, partial)
    for collection in LEGACY_PI_COLLECTIONS:
        await db[collection].create_index(
            [("academy_id", 1), ("stripe_payment_intent", 1)],
            partialFilterExpression={"stripe_payment_intent": dict(_PLANNER_USABLE)},
            name=LEGACY_PI_INDEX,
        )
