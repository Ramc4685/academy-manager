"""Autopay status state machine — Slice B.

Splits "is the parent enrolled in autopay?" (``AutopayEnrollmentStatus``) from
"did the last charge attempt work?" (``AutopayAttemptOutcome``). Conflating
these on one field is the classic dunning-system smell: a bounced charge does
not mean the parent stopped being enrolled in autopay, and mixing outcomes
into the enrollment enum invites code that silently disables autopay on a
transient decline.

Pure domain module — no infra imports.
"""

from __future__ import annotations

from typing import Literal

AutopayEnrollmentStatus = Literal[
    "not_offered",
    "offered",
    "setup_started",
    "active",
    "paused",
    "disabled",
]

AutopayAttemptOutcome = Literal[
    "succeeded",
    "declined",
    "requires_action",
    "error",
]

# Legal enrollment-status transitions. Self-transitions (no-ops) are always
# allowed and are not enumerated here — see `can_transition_autopay_enrollment_status`.
ALLOWED_AUTOPAY_ENROLLMENT_TRANSITIONS: dict[
    AutopayEnrollmentStatus, set[AutopayEnrollmentStatus]
] = {
    "not_offered": {"offered"},
    "offered": {"setup_started", "disabled"},
    "setup_started": {"active", "offered", "disabled"},
    "active": {"paused", "disabled"},
    "paused": {"active", "disabled"},
    "disabled": {"offered"},
}


def can_transition_autopay_enrollment_status(
    current: AutopayEnrollmentStatus,
    target: AutopayEnrollmentStatus,
) -> bool:
    """True if moving from `current` to `target` is a legal enrollment-status
    transition (or a no-op)."""
    if current == target:
        return True
    return target in ALLOWED_AUTOPAY_ENROLLMENT_TRANSITIONS.get(current, set())
