from datetime import date

from backend.v2.contexts.onboarding.domain.waiver_sections import (
    has_age_paths,
    missing_initials,
    parse_sections,
    signing_path_for,
)

BODY = """Intro paragraph.

## Risks [initials]
Badminton has risks.
## Adult release [adult]
I release the academy.
## Parent release [MINOR] [initials]
I release on behalf of my child.
"""


def test_headings_split_the_body_and_tags_mark_sections() -> None:
    sections = parse_sections(BODY)

    assert [(s.key, s.heading, s.initials, s.audience) for s in sections] == [
        ("s1", None, False, "all"),
        ("s2", "Risks", True, "all"),
        ("s3", "Adult release", False, "adult"),
        ("s4", "Parent release", True, "minor"),
    ]
    assert sections[1].body == "Badminton has risks."
    assert has_age_paths(sections)


def test_a_legacy_body_is_one_untitled_section() -> None:
    (only,) = parse_sections("Plain waiver text.\nSecond line.")

    assert only.heading is None and only.body == "Plain waiver text.\nSecond line."
    assert not has_age_paths([only])


def test_eighteenth_birthday_switches_to_the_adult_path() -> None:
    assert signing_path_for("2008-11-02", date(2026, 11, 1)) == "minor"
    assert signing_path_for("2008-11-02", date(2026, 11, 2)) == "adult"
    assert signing_path_for(None, date(2026, 11, 2)) is None
    assert signing_path_for("not a date", date(2026, 11, 2)) is None


def test_only_sections_on_the_signers_path_need_initials() -> None:
    sections = parse_sections(BODY)

    assert missing_initials(sections, "minor", {}) == ["s2", "s4"]
    assert missing_initials(sections, "adult", {"s2": "PP"}) == []
    assert missing_initials(sections, "minor", {"s2": "PP", "s4": "P1"}) == ["s4"]
