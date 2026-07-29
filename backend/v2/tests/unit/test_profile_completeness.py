"""Profile completeness rules — pure, no I/O."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.shared.profile.completeness import (
    MEDICAL_NONE_SENTINEL,
    ChildFacts,
    ParentFacts,
    child_gaps,
    evaluate,
    parent_gaps,
)

CONFIRMED_AT = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def complete_parent(**overrides: object) -> ParentFacts:
    return ParentFacts(
        **{
            "first_name": "Meera",
            "last_name": "Raghavan",
            "phone": "+1 555 0100",
            "email_confirmed_at": CONFIRMED_AT,
            **overrides,
        }
    )


def complete_child(**overrides: object) -> ChildFacts:
    return ChildFacts(
        **{
            "student_id": "stu_1",
            "full_name": "Aanya Raghavan",
            "date_of_birth": "2015-04-02",
            "emergency_contact_name": "Vikram Raghavan",
            "emergency_contact_phone": "+1 555 0111",
            "medical_notes": "Mild peanut allergy",
            **overrides,
        }
    )


def test_fully_populated_profile_has_no_gaps() -> None:
    gaps = evaluate(complete_parent(), [complete_child()])

    assert gaps.parent == []
    assert gaps.children == {"stu_1": []}
    assert gaps.is_complete is True
    assert gaps.total == 0


@pytest.mark.parametrize(
    "field",
    ["first_name", "last_name", "phone"],
)
def test_each_missing_parent_field_is_reported(field: str) -> None:
    assert parent_gaps(complete_parent(**{field: None})) == [field]


def test_unconfirmed_email_is_a_parent_gap() -> None:
    assert parent_gaps(complete_parent(email_confirmed_at=None)) == ["email_confirmed"]


@pytest.mark.parametrize(
    "field",
    [
        "full_name",
        "date_of_birth",
        "emergency_contact_name",
        "emergency_contact_phone",
        "medical_notes",
    ],
)
def test_each_missing_child_field_is_reported(field: str) -> None:
    assert child_gaps(complete_child(**{field: None})) == [field]


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_whitespace_only_counts_as_missing(blank: str) -> None:
    assert child_gaps(complete_child(date_of_birth=blank)) == ["date_of_birth"]
    assert parent_gaps(complete_parent(phone=blank)) == ["phone"]


def test_medical_sentinel_closes_the_medical_gap() -> None:
    """ "No known conditions" is an answer, not an absence."""

    assert child_gaps(complete_child(medical_notes=MEDICAL_NONE_SENTINEL)) == []


def test_medical_free_text_closes_the_medical_gap() -> None:
    assert child_gaps(complete_child(medical_notes="Asthma inhaler in bag")) == []


def test_parent_with_no_children_still_reports_parent_gaps() -> None:
    gaps = evaluate(complete_parent(phone=None), [])

    assert gaps.parent == ["phone"]
    assert gaps.children == {}
    assert gaps.is_complete is False


def test_gaps_are_reported_per_child() -> None:
    gaps = evaluate(
        complete_parent(),
        [
            complete_child(student_id="stu_1"),
            complete_child(student_id="stu_2", date_of_birth=None, medical_notes=None),
        ],
    )

    assert gaps.children == {
        "stu_1": [],
        "stu_2": ["date_of_birth", "medical_notes"],
    }
    assert gaps.is_complete is False
    assert gaps.total == 2


def test_a_complete_parent_with_an_incomplete_child_is_not_complete() -> None:
    gaps = evaluate(complete_parent(), [complete_child(emergency_contact_phone=None)])

    assert gaps.parent == []
    assert gaps.is_complete is False
