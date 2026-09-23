"""The public trial form's dedupe on a real mongod (Lane B4).

Concurrent identical submissions through the real HTTP route, composition
and repository, against the 0192 unique ``(academy_id, dedupe_key)`` index
(every migration replayed by ``real_db``): exactly one ``crm_contacts`` row,
every caller gets byte-identical answers, and the owner is emailed once.
The same inquiry on another academy's host is that academy's own row.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from backend.v2.contexts.enrollment.domain.public_catalog import public_class_id
from backend.v2.tests.fixtures.public_page import ACADEMY, OTHER, RIVERSIDE_HOST, build_app

URL = "/api/v2/public/trial-requests"


def _form() -> dict[str, Any]:
    return {
        "name": "Jamie Testparent",
        "email": "jamie.contract@example.test",
        "player_age": "9",
        "class_id": public_class_id(ACADEMY, "sess-jr-sat"),
        "contact_about_request": True,
    }


async def _seed(db: Any) -> None:
    """Minimal valid documents for the real validators (not the mongomock seed)."""
    await db["academies"].insert_many(
        [
            {
                "academy_id": ACADEMY,
                "display_name": "Riverside Shuttle Club",
                "public_page": {"published": True},
            },
            {
                "academy_id": OTHER,
                "display_name": "Lakeside Racquets",
                "public_page": {"published": True},
            },
        ]
    )
    await db["sessions"].insert_one(
        {
            "academy_id": ACADEMY,
            "session_id": "sess-jr-sat",
            "title": "Juniors Saturday",
            "capacity": 10,
            "amount_cents": 9000,
            "status": "scheduled",
            "days_of_week": ["Sat"],
            "start_time": "09:00",
            "end_time": "10:00",
            "timezone": "America/New_York",
            "published": True,
        }
    )
    await db["academy_memberships"].insert_one(
        {
            "membership_id": "mem-owner-c-1",
            "academy_id": ACADEMY,
            "user_id": "owner-c-1",
            "roles": ["owner"],
            "status": "active",
        }
    )
    await db["users"].insert_one(
        {"user_id": "owner-c-1", "academy_id": ACADEMY, "email": "owner.c@example.test"}
    )


async def test_concurrent_identical_submissions_make_one_row_and_one_answer(real_db: Any) -> None:
    await _seed(real_db)
    app = build_app(real_db)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        responses = await asyncio.gather(
            *[client.post(URL, json=_form(), headers={"host": RIVERSIDE_HOST}) for _ in range(8)]
        )
        other = await client.post(
            URL,
            json={**_form(), "class_id": None},
            headers={"host": "lakeside-academy.courtmastr.test"},
        )

    answers = {
        (
            r.status_code,
            r.content,
            tuple(sorted((k, v) for k, v in r.headers.items() if k != "date")),
        )
        for r in responses
    }
    assert len(answers) == 1, answers
    assert responses[0].status_code == 200 and responses[0].json() == {"state": "received"}
    assert other.status_code == 200

    rows = [doc async for doc in real_db["crm_contacts"].find({})]
    by_academy = sorted(doc["academy_id"] for doc in rows)
    assert by_academy == sorted([ACADEMY, OTHER])
    # One new Riverside row -> one owner email; Lakeside has no address at all.
    assert len(app.state.sent_email.sent) == 1
