"""Public class listing rules and use case (public tenant page, Lane B2).

Fakes here only stand in for reads the use case already receives filtered
(``available_for_public_catalog`` is exercised on a real mongod in
``tests/contract/test_public_catalog_is_academy_scoped.py``); the fake
program store mirrors the real one's "archived is hidden" default.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import pytest

from backend.v2.contexts.enrollment.application.use_cases.public_catalog import (
    ListPublicCatalog,
    PublicCatalogSession,
)
from backend.v2.contexts.enrollment.domain.programs import AgeBand, ClassPublicProfile, Program
from backend.v2.contexts.enrollment.domain.public_catalog import (
    coach_public_name,
    public_class_id,
    public_program_id,
    seat_band,
)

ACADEMY = "acad-riverside"
NOW = datetime(2026, 9, 23, tzinfo=UTC)


# --- domain rules ----------------------------------------------------------


def test_public_class_id_is_stable_opaque_and_tenant_bound() -> None:
    first = public_class_id(ACADEMY, "sess-juniors-sat")
    assert first == public_class_id(ACADEMY, "sess-juniors-sat")
    assert first.startswith("c_") and len(first) == 18
    assert "sess" not in first and "juniors" not in first
    assert first != public_class_id("acad-lakeside", "sess-juniors-sat")
    assert first != public_class_id(ACADEMY, "sess-juniors-sun")
    # A program and a class with the same internal id never collide.
    assert public_program_id(ACADEMY, "sess-juniors-sat")[2:] != first[2:]


def test_public_class_id_does_not_embed_an_object_id() -> None:
    oid = "66f1c0ffee00000000000001"
    assert oid not in public_class_id(ACADEMY, oid)
    assert oid[:8] not in public_class_id(ACADEMY, oid)


@pytest.mark.parametrize(
    ("capacity", "occupied", "expected"),
    [
        (12, 0, ("open", None)),
        (12, 8, ("open", None)),
        (12, 9, ("few", 3)),
        (12, 11, ("few", 1)),
        (12, 12, ("waitlist", None)),
        (12, 15, ("waitlist", None)),  # over-booked still reads as full
        (1, 0, ("few", 1)),
        (0, 0, ("waitlist", None)),
    ],
)
def test_seat_band_never_exposes_counts_above_the_few_threshold(
    capacity: int, occupied: int, expected: tuple[str, int | None]
) -> None:
    assert seat_band(capacity, occupied) == expected


@pytest.mark.parametrize(
    ("name", "display", "expected"),
    [
        ("Alex  Morgan", "full_name", "Alex Morgan"),
        ("Alex Morgan", "first_name", "Alex"),
        ("Alex Morgan", "hidden", None),
        ("coach@example.test", "full_name", None),
        ("coach@example.test", "first_name", None),
        ("", "full_name", None),
        (None, "full_name", None),
    ],
)
def test_coach_public_name(name: str | None, display: str, expected: str | None) -> None:
    assert coach_public_name(name, display) == expected  # type: ignore[arg-type]


# --- use case --------------------------------------------------------------


class _Programs:
    def __init__(self, programs: list[Program]) -> None:
        self._programs = programs

    async def list_all(self, *, include_archived: bool = False) -> list[Program]:
        return [p for p in self._programs if include_archived or not p.archived]


class _Sessions:
    def __init__(self, rows: list[PublicCatalogSession]) -> None:
        self._rows = rows

    async def available_for_public_catalog(self) -> list[PublicCatalogSession]:
        return list(self._rows)


class _Coaches:
    def __init__(self, names: dict[str, str]) -> None:
        self.names = names
        self.asked: list[list[str]] = []

    async def display_names(self, coach_ids: list[str]) -> dict[str, str]:
        self.asked.append(list(coach_ids))
        return {cid: self.names[cid] for cid in coach_ids if cid in self.names}


def _program(program_id: str, name: str, *, sort_order: int = 0, archived: bool = False) -> Program:
    return Program(
        program_id=program_id,
        academy_id=ACADEMY,
        name=name,
        level="Beginner",
        age_band=AgeBand(min_age=6, max_age=9),
        sort_order=sort_order,
        archived=archived,
        created_at=NOW,
        updated_at=NOW,
    )


def _row(session_id: str, **overrides: object) -> PublicCatalogSession:
    profile_fields: dict[str, object] = {"session_id": session_id, "published": True}
    for key in ("program_id", "price_period", "coach_display", "level", "age_band"):
        if key in overrides:
            profile_fields[key] = overrides.pop(key)
    fields: dict[str, object] = {
        "profile": ClassPublicProfile(**profile_fields),  # type: ignore[arg-type]
        "coach_id": "coach-1",
        "title": f"Class {session_id}",
        "days_of_week": ("Sat",),
        "start_time": "09:00",
        "end_time": "10:00",
        "capacity": 12,
        "occupied_seats": 2,
        "amount_cents": 9000,
    }
    fields.update(overrides)
    return PublicCatalogSession(**fields)  # type: ignore[arg-type]


def _run(use_case: ListPublicCatalog, **kwargs: object):  # type: ignore[no-untyped-def]
    return asyncio.run(use_case.execute(ACADEMY, **kwargs))  # type: ignore[arg-type]


def test_groups_published_classes_by_program_in_sort_order() -> None:
    use_case = ListPublicCatalog(
        _Programs([_program("p-adults", "Adults", sort_order=2), _program("p-jr", "Juniors")]),
        _Sessions(
            [
                _row("s-adult", program_id="p-adults"),
                _row("s-jr-sun", program_id="p-jr", days_of_week=("Sun",)),
                _row("s-jr-sat", program_id="p-jr", days_of_week=("Sat",)),
                _row("s-loose"),
            ]
        ),
        _Coaches({"coach-1": "Alex Morgan"}),
    )
    catalog = _run(use_case)
    assert [p.name for p in catalog.programs] == ["Juniors", "Adults"]
    juniors = catalog.programs[0]
    assert juniors.public_id == public_program_id(ACADEMY, "p-jr")
    assert [c.public_id for c in juniors.classes] == [
        public_class_id(ACADEMY, "s-jr-sat"),
        public_class_id(ACADEMY, "s-jr-sun"),
    ]
    # Class inherits the program's level and ages when it sets none.
    assert juniors.classes[0].level == "Beginner"
    assert juniors.classes[0].age_band == AgeBand(min_age=6, max_age=9)
    assert [c.title for c in catalog.ungrouped_classes] == ["Class s-loose"]


def test_archived_program_is_not_listed_and_its_classes_read_as_ungrouped() -> None:
    use_case = ListPublicCatalog(
        _Programs([_program("p-old", "Old squad", archived=True)]),
        _Sessions([_row("s-1", program_id="p-old")]),
        _Coaches({}),
    )
    catalog = _run(use_case)
    assert catalog.programs == ()
    assert [c.title for c in catalog.ungrouped_classes] == ["Class s-1"]


def test_program_without_published_classes_is_not_listed() -> None:
    use_case = ListPublicCatalog(
        _Programs([_program("p-empty", "Empty"), _program("p-jr", "Juniors")]),
        _Sessions([_row("s-1", program_id="p-jr")]),
        _Coaches({}),
    )
    assert [p.name for p in _run(use_case).programs] == ["Juniors"]


def test_unpublished_row_is_dropped_even_if_a_query_returned_it() -> None:
    private = _row("s-private").model_copy(
        update={"profile": ClassPublicProfile(session_id="s-private", published=False)}
    )
    use_case = ListPublicCatalog(_Programs([]), _Sessions([private]), _Coaches({}))
    catalog = _run(use_case)
    assert catalog.programs == () and catalog.ungrouped_classes == ()


def test_full_class_is_listed_as_waitlist_not_dropped() -> None:
    use_case = ListPublicCatalog(
        _Programs([]),
        _Sessions(
            [
                _row("s-full", capacity=10, occupied_seats=10),
                _row("s-few", capacity=10, occupied_seats=8),
                _row("s-open", capacity=10, occupied_seats=1),
            ]
        ),
        _Coaches({}),
    )
    seats = {c.title: c.seats for c in _run(use_case).ungrouped_classes}
    assert seats["Class s-full"] is not None and seats["Class s-full"].band == "waitlist"
    assert seats["Class s-few"] is not None
    assert (seats["Class s-few"].band, seats["Class s-few"].seats_left) == ("few", 2)
    assert seats["Class s-open"] is not None
    assert (seats["Class s-open"].band, seats["Class s-open"].seats_left) == ("open", None)


def test_hidden_price_and_availability_never_leave_the_use_case() -> None:
    use_case = ListPublicCatalog(_Programs([]), _Sessions([_row("s-1")]), _Coaches({}))
    view = _run(use_case, show_price=False, show_availability=False).ungrouped_classes[0]
    assert view.price is None
    assert view.seats is None


def test_price_period_follows_class_then_academy_default() -> None:
    use_case = ListPublicCatalog(
        _Programs([]),
        _Sessions([_row("s-own", price_period="class"), _row("s-default")]),
        _Coaches({}),
    )
    views = {c.title: c for c in _run(use_case, price_period_default="term").ungrouped_classes}
    assert views["Class s-own"].price is not None
    assert views["Class s-own"].price.period == "class"
    assert views["Class s-default"].price is not None
    assert views["Class s-default"].price.period == "term"
    assert views["Class s-default"].price.amount_cents == 9000


def test_class_without_a_price_shows_none_rather_than_a_guess() -> None:
    use_case = ListPublicCatalog(
        _Programs([]), _Sessions([_row("s-1", amount_cents=None)]), _Coaches({})
    )
    assert _run(use_case).ungrouped_classes[0].price is None


def test_coach_display_is_honoured_and_hidden_coaches_are_not_looked_up() -> None:
    coaches = _Coaches({"coach-1": "Alex Morgan", "coach-2": "Sam Rivers"})
    use_case = ListPublicCatalog(
        _Programs([]),
        _Sessions(
            [
                _row("s-full", coach_display="full_name"),
                _row("s-first", coach_display="first_name"),
                _row("s-hidden", coach_display="hidden", coach_id="coach-2"),
            ]
        ),
        coaches,
    )
    names = {c.title: c.coach_name for c in _run(use_case).ungrouped_classes}
    assert names == {"Class s-full": "Alex Morgan", "Class s-first": "Alex", "Class s-hidden": None}
    assert coaches.asked == [["coach-1"]]


def test_one_off_class_sorts_by_date_and_keeps_its_date() -> None:
    use_case = ListPublicCatalog(
        _Programs([]),
        _Sessions(
            [
                _row("s-weekly"),
                _row("s-camp", days_of_week=(), starts_on=date(2026, 10, 3)),
            ]
        ),
        _Coaches({}),
    )
    views = _run(use_case).ungrouped_classes
    assert [v.title for v in views] == ["Class s-weekly", "Class s-camp"]
    assert views[1].starts_on == date(2026, 10, 3)


def test_no_rows_short_circuits_without_reading_programs_or_coaches() -> None:
    class _Boom:
        async def list_all(self, *, include_archived: bool = False) -> list[Program]:
            raise AssertionError("programs read for an empty catalog")

    coaches = _Coaches({})
    catalog = _run(ListPublicCatalog(_Boom(), _Sessions([]), coaches))
    assert catalog.programs == () and catalog.ungrouped_classes == ()
    assert coaches.asked == []
