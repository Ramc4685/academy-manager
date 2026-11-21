"""The pure sibling-discount rule (L9 C1): full-price child, applies_to, tie-breaks."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.billing.domain.sibling_discount import (
    FamilyEnrollment,
    full_price_student,
    is_sibling_discounted,
)


def _row(eid: str, sid: str, fee: int, start: datetime | None = None) -> FamilyEnrollment:
    return FamilyEnrollment(
        enrollment_id=eid, student_id=sid, list_fee_cents=fee, enrolled_at=start
    )


def _pick(family: list[FamilyEnrollment], full: str, applies: str = "all_classes") -> set[str]:
    """Every discounted enrollment when the whole family is priced together."""
    full_price = full_price_student(family, full_price_child=full)  # type: ignore[arg-type]
    if full_price is None:
        return set()
    return {
        row.enrollment_id
        for row in family
        if is_sibling_discounted(family, row, full_price=full_price, applies_to=applies)  # type: ignore[arg-type]
    }


def test_equal_tuition_ties_go_to_the_lowest_student_id() -> None:
    family = [_row("e2", "stu-b", 8_000), _row("e1", "stu-a", 8_000)]
    assert _pick(family, "highest_tuition") == {"e2"}
    assert _pick(family, "lowest_tuition") == {"e2"}


def test_tuition_is_the_sum_of_a_childs_list_fees() -> None:
    family = [_row("a1", "stu-a", 10_000), _row("b1", "stu-b", 6_000), _row("b2", "stu-b", 6_000)]
    assert _pick(family, "highest_tuition") == {"a1"}  # Ben's 120.00 beats Ava's 100.00


def test_first_enrolled_uses_the_earliest_start_and_unknown_starts_last() -> None:
    early = datetime(2025, 1, 1, tzinfo=UTC)
    late = datetime(2025, 6, 1)  # naive, as Mongo returns it
    family = [_row("a1", "stu-a", 5_000, late), _row("b1", "stu-b", 5_000, early)]
    assert _pick(family, "first_enrolled") == {"a1"}
    unknown = [_row("a1", "stu-a", 5_000, None), _row("b1", "stu-b", 5_000, late)]
    assert _pick(unknown, "first_enrolled") == {"a1"}


def test_one_class_per_child_takes_the_highest_fee_then_the_lowest_enrollment_id() -> None:
    family = [
        _row("a1", "stu-a", 20_000),
        _row("b2", "stu-b", 7_000),
        _row("b1", "stu-b", 7_000),
        _row("b3", "stu-b", 3_000),
    ]
    assert _pick(family, "highest_tuition", "one_class_per_child") == {"b1"}


def test_fewer_than_two_children_gets_nothing() -> None:
    assert full_price_student([], full_price_child="highest_tuition") is None
    assert _pick([], "highest_tuition") == set()
    assert _pick([_row("a1", "stu-a", 1), _row("a2", "stu-a", 2)], "lowest_tuition") == set()
