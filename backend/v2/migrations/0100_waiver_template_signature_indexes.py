"""Waiver template + signature indexes (Wave 4).

Adds the indexes required by the per-student waiver signature model
documented in ``docs/requirements/2026-05-21-saas-data-model-architecture-assessment.md``
§8 ("Waivers Need Template, Signature, And Artifact Separation").

Collections:

  waiver_templates
    - unique(waiver_template_id)
    - unique(academy_id, version)            one published version per academy
    - index(academy_id, status, effective_from desc)  latest active lookup

  waiver_signatures
    - unique(waiver_signature_id)
    - index(academy_id, student_id, signed_at desc)   latest signature per student
    - index(academy_id, waiver_template_id)           "who signed which template"
    - index(academy_id, parent_user_id)               parent dashboard
    - index(academy_id, artifact_id) sparse           artifact -> signature lookup
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0100_waiver_template_signature_indexes"


async def up(db: AsyncIOMotorDatabase) -> None:
    templates = db["waiver_templates"]
    await templates.create_index(
        "waiver_template_id",
        unique=True,
        name="waiver_template_id_unique",
        partialFilterExpression={"waiver_template_id": {"$type": "string"}},
    )
    await templates.create_index(
        [("academy_id", 1), ("version", 1)],
        unique=True,
        name="waiver_templates_academy_version_unique",
    )
    await templates.create_index(
        [("academy_id", 1), ("status", 1), ("effective_from", -1)],
        name="waiver_templates_active_lookup",
    )

    signatures = db["waiver_signatures"]
    await signatures.create_index(
        "waiver_signature_id",
        unique=True,
        name="waiver_signature_id_unique",
        partialFilterExpression={"waiver_signature_id": {"$type": "string"}},
    )
    await signatures.create_index(
        [("academy_id", 1), ("student_id", 1), ("signed_at", -1)],
        name="waiver_signatures_student_latest",
    )
    await signatures.create_index(
        [("academy_id", 1), ("waiver_template_id", 1)],
        name="waiver_signatures_by_template",
    )
    await signatures.create_index(
        [("academy_id", 1), ("parent_user_id", 1)],
        name="waiver_signatures_by_parent",
    )
    await signatures.create_index(
        [("academy_id", 1), ("artifact_id", 1)],
        name="waiver_signatures_by_artifact",
        sparse=True,
    )
