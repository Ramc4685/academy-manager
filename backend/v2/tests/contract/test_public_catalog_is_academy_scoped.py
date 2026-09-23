"""The public class listing on a real mongod (public tenant page, Lane B2).

``available_for_public_catalog`` is the sibling of the parent catalog that
keeps full classes. On the real indexes and validators (every migration
replayed by ``real_db``): it reads only the academy in scope, only published
listable classes, counts seat-holding enrollments (active and held, not
withdrawn), and the composed public read turns a full class into a
``waitlist`` band instead of dropping it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from backend.v2.composition.public_page_read import compose_public_page_read
from backend.v2.contexts.enrollment.domain.public_catalog import public_class_id
from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import (
    MongoSessionRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope

ACADEMY = "acad-contract-riverside"
OTHER = "acad-contract-lakeside"


def _session(session_id: str, academy_id: str = ACADEMY, **fields: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "academy_id": academy_id,
        "session_id": session_id,
        "coach_id": "coach-contract-1",
        "title": f"Class {session_id}",
        "location": "Main hall",
        "capacity": 3,
        "amount_cents": 8000,
        "status": "scheduled",
        "days_of_week": ["Sat"],
        "start_time": "09:00",
        "end_time": "10:00",
        "timezone": "America/New_York",
    }
    doc.update(fields)
    return doc


async def _seed(db: Any) -> None:
    now = datetime.now(UTC)
    await db["academies"].insert_many(
        [
            {"academy_id": ACADEMY, "display_name": "Riverside Shuttle Club"},
            {"academy_id": OTHER, "display_name": "Lakeside Racquets"},
        ]
    )
    await db["sessions"].insert_many(
        [
            _session("s-full", published=True),
            _session("s-open", published=True, capacity=12),
            _session("s-private"),
            _session("s-cancelled", published=True, status="cancelled"),
            _session("s-ended", published=True, end_date="2020-01-31"),
            _session("s-other", academy_id=OTHER, published=True),
        ]
    )
    one_off_future = _session("s-camp", published=True, start_at=now + timedelta(days=5))
    one_off_past = _session("s-past", published=True, start_at=now - timedelta(days=5))
    for doc in (one_off_future, one_off_past):
        for key in ("days_of_week", "start_time", "end_time"):
            doc.pop(key)
        doc["end_at"] = doc["start_at"] + timedelta(hours=1)
    await db["sessions"].insert_many([one_off_future, one_off_past])
    await db["enrollments"].insert_many(
        [
            {
                "academy_id": academy_id,
                "enrollment_id": f"e-{academy_id}-{i}",
                "session_id": "s-full",
                "student_id": f"stu-{academy_id}-{i}",
                "status": status,
            }
            for academy_id in (ACADEMY, OTHER)
            for i, status in enumerate(["active", "held", "withdrawn"])
        ]
    )


async def test_sibling_read_keeps_full_classes_and_stays_in_its_tenant(real_db: Any) -> None:
    await _seed(real_db)
    # s-full holds 2 of 3 seats; a reservation floor fills it.
    await real_db["sessions"].update_one(
        {"academy_id": ACADEMY, "session_id": "s-full"}, {"$set": {"reserved_seats": 3}}
    )
    with tenant_scope(ACADEMY):
        rows = await MongoSessionRepository(real_db).available_for_public_catalog()
        parent_rows = await MongoSessionRepository(real_db).available_for_parent_catalog()

    by_id = {row.profile.session_id: row for row in rows}
    assert set(by_id) == {"s-full", "s-open", "s-camp"}
    assert by_id["s-full"].occupied_seats == 3 and by_id["s-full"].capacity == 3
    assert by_id["s-camp"].starts_on is not None
    assert by_id["s-camp"].start_time is not None
    # The parent catalog is unchanged: it still drops the full class.
    assert "s-full" not in {row.session_id for row in parent_rows}


async def test_seat_holding_counts_active_and_held_not_withdrawn(real_db: Any) -> None:
    await _seed(real_db)
    with tenant_scope(ACADEMY):
        rows = await MongoSessionRepository(real_db).available_for_public_catalog()
    full = next(row for row in rows if row.profile.session_id == "s-full")
    assert full.occupied_seats == 2  # the other academy's enrollments are not counted


async def test_composed_public_read_is_academy_scoped(real_db: Any) -> None:
    await _seed(real_db)
    await real_db["sessions"].update_one(
        {"academy_id": ACADEMY, "session_id": "s-full"}, {"$set": {"reserved_seats": 3}}
    )
    read = compose_public_page_read(real_db)
    with tenant_scope(ACADEMY):
        catalog = await read.list_catalog.execute(ACADEMY)
    seats = {view.public_id: view.seats for view in catalog.ungrouped_classes}
    full = seats[public_class_id(ACADEMY, "s-full")]
    assert full is not None and full.band == "waitlist"
    assert public_class_id(ACADEMY, "s-other") not in seats
    assert public_class_id(OTHER, "s-other") not in seats

    with tenant_scope(OTHER):
        other = await read.list_catalog.execute(OTHER)
    assert [v.public_id for v in other.ungrouped_classes] == [public_class_id(OTHER, "s-other")]


async def test_published_read_uses_the_0194_index(real_db: Any) -> None:
    await _seed(real_db)
    plan = await real_db.command(
        {
            "explain": {
                "find": "sessions",
                "filter": {
                    "academy_id": ACADEMY,
                    "published": True,
                    "status": {"$nin": ["cancelled", "completed"]},
                },
            },
            "verbosity": "queryPlanner",
        }
    )
    assert "sessions_academy_published" in str(plan["queryPlanner"]["winningPlan"])
