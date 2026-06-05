"""Level-up recommendation, certificate, and coach skill note indexes."""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0122"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    # --- level_up_recommendations ---
    recs = db["level_up_recommendations"]
    await recs.create_index(
        [("academy_id", 1), ("status", 1)],
        name="recs_by_status",
    )
    await recs.create_index(
        [("academy_id", 1), ("student_id", 1), ("program_id", 1)],
        name="recs_by_student_program",
    )
    await recs.create_index(
        [("academy_id", 1), ("student_id", 1), ("from_level_id", 1)],
        unique=True,
        name="recs_active_unique",
        partialFilterExpression={"status": {"$in": ["RECOMMENDED", "APPROVED"]}},
    )
    await recs.create_index(
        "rec_id",
        unique=True,
        name="rec_id_unique",
    )

    # --- skill_certificates ---
    certs = db["skill_certificates"]
    await certs.create_index(
        [("academy_id", 1), ("student_id", 1)],
        name="certs_by_student",
    )
    await certs.create_index(
        "cert_number",
        unique=True,
        name="cert_number_unique",
    )
    await certs.create_index(
        "cert_id",
        unique=True,
        name="cert_id_unique",
    )

    # --- coach_skill_notes ---
    notes = db["coach_skill_notes"]
    await notes.create_index(
        [("academy_id", 1), ("student_id", 1), ("skill_id", 1)],
        name="skill_notes_by_student_skill",
    )
    await notes.create_index(
        [("academy_id", 1), ("coach_id", 1)],
        name="skill_notes_by_coach",
    )
    await notes.create_index(
        "note_id",
        unique=True,
        name="skill_note_id_unique",
    )
