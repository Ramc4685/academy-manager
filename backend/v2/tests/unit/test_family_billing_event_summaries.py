# backend/v2/tests/unit/test_family_billing_event_summaries.py
"""Every enrollment lifecycle event type must have a family-timeline label.

family_billing.py cannot import
backend.v2.contexts.enrollment.domain.events.EnrollmentLifecycleEventType
(Rule 5, no cross-context imports — see the module's own comment above
_EVENT_SUMMARIES), so this test is the tripwire: it imports the real Literal
from the enrollment context and asserts _EVENT_SUMMARIES covers every one of
its members. A held/returned/dropped/... row with no entry falls back to
rendering its raw event_type string in the family timeline instead of
admin-readable text — this is the regression that left the departures/hold
event types blank.
"""

from __future__ import annotations

import typing

from backend.v2.contexts.billing.application.family_billing import _EVENT_SUMMARIES
from backend.v2.contexts.enrollment.domain.events import EnrollmentLifecycleEventType


def test_every_enrollment_lifecycle_event_type_has_a_display_label() -> None:
    writable_event_types = set(typing.get_args(EnrollmentLifecycleEventType))

    missing = writable_event_types - _EVENT_SUMMARIES.keys()

    assert not missing, (
        "these enrollment event types have no family-timeline label and "
        f"render blank/raw: {sorted(missing)}"
    )


def test_event_summaries_has_no_stale_entries() -> None:
    """Catch the inverse drift: a label for a type the domain no longer writes."""
    writable_event_types = set(typing.get_args(EnrollmentLifecycleEventType))

    stale = _EVENT_SUMMARIES.keys() - writable_event_types

    assert not stale, f"these _EVENT_SUMMARIES keys are not writable event types: {sorted(stale)}"
