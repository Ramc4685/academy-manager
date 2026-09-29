"""Pin: a lesson card stored without a ``source`` still cites "Shuttle Time".

Row 13 (academy sport field + curriculum gating) deliberately leaves
``LessonCard.source``'s domain default untouched. BLNO's stored cards predate
the ``sport`` field and never wrote ``source`` explicitly; if the default
ever drifted off ``"BWF_SHUTTLE_TIME"``, the digest's citation
(``digest_renderer._card_citation``) would silently drop "Shuttle Time" for
every academy, sport-neutral or not. This test locks the default and the
citation label together so a future edit to either breaks loudly here
instead of silently in a sent email.
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.communications.application.digest_renderer import _card_citation
from backend.v2.contexts.curriculum.domain.models import LessonCard


def _card(**overrides: object) -> LessonCard:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    values: dict[str, object] = {
        "card_id": "card_001",
        "academy_id": "acad_blno_badminton",
        "program_id": "prog_001",
        "level_id": "level_001",
        "slug": "grip-and-ready-position",
        "lesson_number": 1,
        "title": "Grip and ready position",
        "module_name": "Grip and Movement",
        "lesson_range": "1-2",
        "page_hint": "16-30",
        "created_at": now,
        "updated_at": now,
        "created_by": "system",
    }
    values.update(overrides)
    return LessonCard(**values)  # type: ignore[arg-type]


def test_lesson_card_without_explicit_source_defaults_to_bwf_shuttle_time() -> None:
    # Mirrors a doc stored before the ``source`` field existed: the key is
    # simply absent, so pydantic falls back to the domain default.
    card = _card()
    assert card.source == "BWF_SHUTTLE_TIME"


def test_card_citation_for_default_source_says_shuttle_time() -> None:
    card = _card()
    citation = _card_citation(card)
    assert citation.startswith("Shuttle Time, Grip and Movement, 1-2")
    assert "p.16-30" in citation


def test_card_citation_for_academy_custom_source_is_unlabelled() -> None:
    # A non-badminton academy's custom cards must not be mislabelled as
    # Shuttle Time content.
    card = _card(source="ACADEMY_CUSTOM", module_name="Fundamentals", lesson_range="1")
    citation = _card_citation(card)
    assert "Shuttle Time" not in citation
    assert citation.startswith("ACADEMY_CUSTOM, Fundamentals, 1")
