"""The real GET /coach/academy reader: field names against a stored academies doc."""

from __future__ import annotations

import asyncio

from mongomock_motor import AsyncMongoMockClient

from backend.v2.composition.coach import _coach_academy_info


def test_reads_the_academy_contact_pair_from_the_academies_doc() -> None:
    db = AsyncMongoMockClient()["coach_info"]

    async def run() -> dict[str, object]:
        await db["academies"].insert_one(
            {
                "academy_id": "acad-1",
                "display_name": "Riverside",
                "contact_email": "office@example.com",
                "contact_phone": "555-0142",
            }
        )
        result: dict[str, object] = await _coach_academy_info(db)(academy_id="acad-1")
        return result

    info = asyncio.run(run())
    assert info["name"] == "Riverside"
    assert (info["contact_email"], info["contact_phone"]) == ("office@example.com", "555-0142")
