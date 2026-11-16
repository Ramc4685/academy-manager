"""Automatic sibling discount: which of a family's enrollments are discounted (L9 C1).

Pure rule, no I/O. The monthly resolver gathers one family's eligible
enrollments for a month (same resolved ``parent_id``; active, monthly-invoiced,
list fee > 0) and asks which of them get the owner's sibling percentage.

* One child pays full price, chosen by ``full_price_child``:
  ``highest_tuition`` / ``lowest_tuition`` compare each child's summed list
  fees; ``first_enrolled`` takes the child with the earliest enrollment.
  Ties go to the lowest ``student_id``.
* Every other child is discounted: on all their classes (``all_classes``), or
  on one class each (``one_class_per_child``: the highest list fee, ties to the
  lowest ``enrollment_id``).
* A family with fewer than two eligible children gets no sibling discount.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

from backend.v2.contexts.billing.domain.billing_settings import (
    SiblingAppliesTo,
    SiblingFullPriceChild,
)
from backend.v2.contexts.billing.domain.tuition_discount import TuitionDiscount

#: Category of the synthetic policy; its display label is "Sibling discount".
SIBLING_CATEGORY = "sibling"


@dataclass(frozen=True)
class FamilyEnrollment:
    enrollment_id: str
    student_id: str
    list_fee_cents: int
    #: When the enrollment started; ``None`` sorts last for ``first_enrolled``.
    enrolled_at: datetime | None = None


def sibling_discounted_enrollment_ids(
    family: Sequence[FamilyEnrollment],
    *,
    full_price_child: SiblingFullPriceChild,
    applies_to: SiblingAppliesTo,
) -> frozenset[str]:
    by_child: dict[str, list[FamilyEnrollment]] = defaultdict(list)
    for row in family:
        by_child[row.student_id].append(row)
    if len(by_child) < 2:
        return frozenset()

    def tuition(student_id: str) -> int:
        return sum(row.list_fee_cents for row in by_child[student_id])

    def first_start(student_id: str) -> tuple[bool, datetime]:
        starts = [_utc_naive(row.enrolled_at) for row in by_child[student_id] if row.enrolled_at]
        # Unknown start dates sort after every known one.
        return (not starts, min(starts) if starts else datetime.max)

    # student_id is the last key everywhere: ties go to the lowest id.
    if full_price_child == "highest_tuition":
        full_price = min(by_child, key=lambda sid: (-tuition(sid), sid))
    elif full_price_child == "lowest_tuition":
        full_price = min(by_child, key=lambda sid: (tuition(sid), sid))
    else:
        full_price = min(by_child, key=lambda sid: (*first_start(sid), sid))

    discounted: set[str] = set()
    for student_id in by_child:
        if student_id == full_price:
            continue
        rows = by_child[student_id]
        if applies_to == "all_classes":
            discounted.update(row.enrollment_id for row in rows)
        else:
            pick = min(rows, key=lambda row: (-row.list_fee_cents, row.enrollment_id))
            discounted.add(pick.enrollment_id)
    return frozenset(discounted)


def sibling_policy(
    *, enrollment_id: str, student_id: str, period: str, percent_bps: int, period_start: date
) -> TuitionDiscount:
    """The synthetic percent policy the resolver weighs against a manual one."""
    return TuitionDiscount(
        discount_id=f"sibling-auto-{period}",
        enrollment_id=enrollment_id,
        student_id=student_id,
        category=SIBLING_CATEGORY,
        kind="percent",
        percent_bps=percent_bps,
        effective_start=period_start,
    )


def _utc_naive(at: datetime) -> datetime:
    # Mongo hands back naive UTC datetimes; compare everything naive UTC.
    return at.astimezone(UTC).replace(tzinfo=None) if at.tzinfo else at
