"""Which enrollments are billed: the one ``billing_type`` predicate every context shares.

An enrollment's ``billing_type`` decides whether the monthly run invoices it.
A missing value reads ``standard``; the CSV importer writes ``Standard``,
``NoCharge`` and ``Waived``; comparisons are case-insensitive. Anything
outside :data:`MONTHLY_INVOICED_BILLING_TYPES` is **not billed**: the child
still attends (rosters, attendance, skills) but is left out of every student
headcount, sibling family and payroll revenue base.

Lives in ``shared`` because billing, enrollment, reporting and coaching all
read it and contexts may not import one another.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

#: ``billing_type`` values the monthly run invoices (lower-cased; missing is "").
MONTHLY_INVOICED_BILLING_TYPES: Final[frozenset[str]] = frozenset(
    {"", "standard", "monthly", "manual"}
)

#: The value an admin's "Not billed" writes: the importer's spelling, so prod
#: rows and new rows share one stored value.
NOT_BILLED_BILLING_TYPE: Final = "NoCharge"

#: Why a child is not billed. Labels live in the UI; the route's Literal mirrors it.
NOT_BILLED_REASONS: Final[tuple[str, ...]] = (
    "owner_child",
    "coach_child",
    "scholarship",
    "other",
)


def normalized_billing_type(value: object) -> str:
    return str(value or "").lower()


def is_not_billed(enrollment: Mapping[str, Any]) -> bool:
    """True when the monthly run never invoices this enrollment."""
    return normalized_billing_type(enrollment.get("billing_type")) not in (
        MONTHLY_INVOICED_BILLING_TYPES
    )


#: A Mongo ``$match``/``find`` clause selecting the BILLED enrollments, the
#: same rule as :func:`is_not_billed`. ``$expr`` so it composes with a query's
#: own ``$or`` without clashing.
BILLED_ENROLLMENT_FILTER: Final[dict[str, Any]] = {
    "$expr": {
        "$in": [
            {"$toLower": {"$ifNull": ["$billing_type", ""]}},
            sorted(MONTHLY_INVOICED_BILLING_TYPES),
        ]
    }
}
NOT_BILLED_ENROLLMENT_FILTER: Final[dict[str, Any]] = {
    "$expr": {"$not": [BILLED_ENROLLMENT_FILTER["$expr"]]}
}
