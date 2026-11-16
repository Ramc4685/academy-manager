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
from backend.v2.contexts.billing.domain.tuition_discount import (
    TuitionDiscount,
    monthly_discount_cents,
)

#: Category of the synthetic policy; its display label is "Sibling discount".
SIBLING_CATEGORY = "sibling"
#: ``discount_id`` prefix of the synthetic policy, so an invoice's discount line
#: says whether the month was priced with it.
SIBLING_DISCOUNT_ID_PREFIX = "sibling-auto-"


@dataclass(frozen=True)
class FamilyEnrollment:
    enrollment_id: str
    student_id: str
    list_fee_cents: int
    #: When the enrollment started; ``None`` sorts last for ``first_enrolled``.
    enrolled_at: datetime | None = None


def full_price_student(
    family: Sequence[FamilyEnrollment], *, full_price_child: SiblingFullPriceChild
) -> str | None:
    """The child who pays full price among ``family``, or ``None`` when empty."""
    by_child: dict[str, list[FamilyEnrollment]] = defaultdict(list)
    for row in family:
        by_child[row.student_id].append(row)
    if not by_child:
        return None

    def tuition(student_id: str) -> int:
        return sum(row.list_fee_cents for row in by_child[student_id])

    def first_start(student_id: str) -> tuple[bool, datetime]:
        starts = [_utc_naive(row.enrolled_at) for row in by_child[student_id] if row.enrolled_at]
        # Unknown start dates sort after every known one.
        return (not starts, min(starts) if starts else datetime.max)

    # student_id is the last key everywhere: ties go to the lowest id.
    if full_price_child == "highest_tuition":
        return min(by_child, key=lambda sid: (-tuition(sid), sid))
    if full_price_child == "lowest_tuition":
        return min(by_child, key=lambda sid: (tuition(sid), sid))
    return min(by_child, key=lambda sid: (*first_start(sid), sid))


def is_sibling_discounted(
    family: Sequence[FamilyEnrollment],
    enrollment: FamilyEnrollment,
    *,
    full_price: str,
    applies_to: SiblingAppliesTo,
) -> bool:
    """Whether ``enrollment`` is discounted, given the full-price child.

    Every other child is discounted on all their classes, or on one class
    each (the highest list fee in ``family``, ties to the lowest id).
    """
    if enrollment.student_id == full_price:
        return False
    if applies_to == "all_classes":
        return True
    own = [row for row in family if row.student_id == enrollment.student_id] or [enrollment]
    pick = min(own, key=lambda row: (-row.list_fee_cents, row.enrollment_id))
    return pick.enrollment_id == enrollment.enrollment_id


def sibling_discounted_enrollment_ids(
    family: Sequence[FamilyEnrollment],
    *,
    full_price_child: SiblingFullPriceChild,
    applies_to: SiblingAppliesTo,
) -> frozenset[str]:
    """Every discounted enrollment when the whole family is priced together."""
    if len({row.student_id for row in family}) < 2:
        return frozenset()
    full_price = full_price_student(family, full_price_child=full_price_child)
    if full_price is None:  # pragma: no cover - two children were just counted
        return frozenset()
    return frozenset(
        row.enrollment_id
        for row in family
        if is_sibling_discounted(family, row, full_price=full_price, applies_to=applies_to)
    )


def sibling_policy(
    *, enrollment_id: str, student_id: str, period: str, percent_bps: int, period_start: date
) -> TuitionDiscount:
    """The synthetic percent policy the resolver weighs against a manual one."""
    return TuitionDiscount(
        discount_id=f"{SIBLING_DISCOUNT_ID_PREFIX}{period}",
        enrollment_id=enrollment_id,
        student_id=student_id,
        category=SIBLING_CATEGORY,
        kind="percent",
        percent_bps=percent_bps,
        effective_start=period_start,
    )


def best_tuition_discount(
    manual: TuitionDiscount | None, sibling: TuitionDiscount | None, *, monthly_price_cents: int
) -> TuitionDiscount | None:
    """One discount line per invoice: the larger of the manual policy and the
    sibling one at this price, never both. Manual wins a tie."""
    if sibling is None:
        return manual
    if manual is None:
        return sibling
    manual_cents = monthly_discount_cents(manual, monthly_price_cents=monthly_price_cents)
    sibling_cents = monthly_discount_cents(sibling, monthly_price_cents=monthly_price_cents)
    return sibling if sibling_cents > manual_cents else manual


def _utc_naive(at: datetime) -> datetime:
    # Mongo hands back naive UTC datetimes; compare everything naive UTC.
    return at.astimezone(UTC).replace(tzinfo=None) if at.tzinfo else at
