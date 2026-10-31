"""Resolving the trial form's opaque class id (public tenant page, Lane B4)."""

from __future__ import annotations

from backend.v2.contexts.enrollment.application.use_cases.public_catalog import (
    PublicCatalogSession,
)
from backend.v2.contexts.enrollment.application.use_cases.public_class_choice import (
    ResolvePublicClassChoice,
)
from backend.v2.contexts.enrollment.domain.programs import ClassPublicProfile
from backend.v2.contexts.enrollment.domain.public_catalog import public_class_id

ACADEMY = "acad-riverside"


def _row(session_id: str, *, published: bool = True, capacity: int = 10, occupied: int = 0):
    return PublicCatalogSession(
        profile=ClassPublicProfile(session_id=session_id, published=published),
        title=f"Class {session_id}",
        capacity=capacity,
        occupied_seats=occupied,
    )


class _Sessions:
    def __init__(self, rows: list[PublicCatalogSession]) -> None:
        self.rows = rows

    async def available_for_public_catalog(self) -> list[PublicCatalogSession]:
        return self.rows


async def test_matches_only_a_published_class_of_this_academy() -> None:
    use_case = ResolvePublicClassChoice(
        _Sessions([_row("s-open"), _row("s-private", published=False)])
    )
    hit = await use_case.execute(ACADEMY, public_class_id(ACADEMY, "s-open"))
    assert hit.chosen is not None and hit.chosen.session_id == "s-open"
    assert hit.chosen.full is False and not hit.unknown_id

    private = await use_case.execute(ACADEMY, public_class_id(ACADEMY, "s-private"))
    assert private.chosen is None and private.unknown_id

    # The same session id under another academy's digest does not match.
    foreign = await use_case.execute(ACADEMY, public_class_id("acad-lakeside", "s-open"))
    assert foreign.chosen is None and foreign.unknown_id


async def test_reports_full_classes_and_whether_anything_is_open() -> None:
    use_case = ResolvePublicClassChoice(_Sessions([_row("s-full", capacity=2, occupied=2)]))
    result = await use_case.execute(ACADEMY, public_class_id(ACADEMY, "s-full"))
    assert result.chosen is not None and result.chosen.full is True
    assert result.has_classes is True and result.any_open is False

    blank = await use_case.execute(ACADEMY, "  ")
    assert blank.chosen is None and blank.unknown_id is False


async def test_nothing_listed() -> None:
    result = await ResolvePublicClassChoice(_Sessions([])).execute(ACADEMY, None)
    assert (result.has_classes, result.any_open, result.chosen, result.unknown_id) == (
        False,
        False,
        None,
        False,
    )
