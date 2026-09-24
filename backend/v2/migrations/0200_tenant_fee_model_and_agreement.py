"""Backfill the tenant fee model and platform agreement fields (roadmap L9c).

L9c adds ``fee_model`` and the platform agreement acceptance fields
(``platform_agreement_version``, ``platform_agreement_accepted_at``,
``platform_agreement_accepted_by``) to the tenant record in ``academies``.

* ``fee_model`` is set to ``"flat_monthly"`` (owner decision 2026-09-22) on
  every academy that has no fee model yet.
* The three agreement fields are set to ``null`` on every academy that lacks
  them. This is deliberately NOT an acceptance: the existing academy has not
  accepted a written platform agreement, so none is fabricated. Activation
  checks these fields only on the ``provisioning -> active`` transition, so an
  academy that is already active keeps serving.

Idempotent: each update only touches documents missing the field, so a re-run
is a no-op and a recorded acceptance is never overwritten. No index: the
fields are read with the tenant document by ``academy_id``.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0200_tenant_fee_model_and_agreement"

DEFAULT_FEE_MODEL = "flat_monthly"
AGREEMENT_FIELDS = (
    "platform_agreement_version",
    "platform_agreement_accepted_at",
    "platform_agreement_accepted_by",
)


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    academies = db["academies"]
    await academies.update_many(
        {"fee_model": {"$exists": False}},
        {"$set": {"fee_model": DEFAULT_FEE_MODEL}},
    )
    for field in AGREEMENT_FIELDS:
        await academies.update_many(
            {field: {"$exists": False}},
            {"$set": {field: None}},
        )
