"""Unit tests — autopay_enrollment_status state-machine transitions (Slice B)."""

from __future__ import annotations

import pytest

from backend.v2.contexts.billing.domain.autopay_status import (
    ALLOWED_AUTOPAY_ENROLLMENT_TRANSITIONS,
    AutopayEnrollmentStatus,
    can_transition_autopay_enrollment_status,
)

ALL_STATUSES: tuple[AutopayEnrollmentStatus, ...] = (
    "not_offered",
    "offered",
    "setup_started",
    "active",
    "paused",
    "disabled",
)

LEGAL_TRANSITIONS = [
    ("not_offered", "offered"),
    ("offered", "setup_started"),
    ("offered", "disabled"),
    ("setup_started", "active"),
    ("setup_started", "offered"),
    ("setup_started", "disabled"),
    ("active", "paused"),
    ("active", "disabled"),
    ("paused", "active"),
    ("paused", "disabled"),
    ("disabled", "offered"),
]


@pytest.mark.parametrize(("current", "target"), LEGAL_TRANSITIONS)
def test_legal_transitions_allowed(
    current: AutopayEnrollmentStatus, target: AutopayEnrollmentStatus
) -> None:
    assert can_transition_autopay_enrollment_status(current, target) is True


@pytest.mark.parametrize("status", ALL_STATUSES)
def test_self_transition_is_always_a_noop_allowed(status: AutopayEnrollmentStatus) -> None:
    assert can_transition_autopay_enrollment_status(status, status) is True


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (current, target)
        for current in ALL_STATUSES
        for target in ALL_STATUSES
        if current != target and (current, target) not in LEGAL_TRANSITIONS
    ],
)
def test_illegal_transitions_rejected(
    current: AutopayEnrollmentStatus, target: AutopayEnrollmentStatus
) -> None:
    assert can_transition_autopay_enrollment_status(current, target) is False


def test_not_offered_cannot_jump_directly_to_active() -> None:
    assert can_transition_autopay_enrollment_status("not_offered", "active") is False


def test_paused_cannot_jump_directly_to_setup_started() -> None:
    assert can_transition_autopay_enrollment_status("paused", "setup_started") is False


def test_active_cannot_go_back_to_offered() -> None:
    assert can_transition_autopay_enrollment_status("active", "offered") is False


def test_disabled_is_terminal_except_for_re_offering() -> None:
    for target in ALL_STATUSES:
        expected = target in ("disabled", "offered")
        assert can_transition_autopay_enrollment_status("disabled", target) is expected


def test_every_status_has_an_explicit_transition_entry() -> None:
    # Every non-terminal-forever status should be represented explicitly so
    # future states can't silently fall back to an empty transition set.
    for status in ALL_STATUSES:
        assert status in ALLOWED_AUTOPAY_ENROLLMENT_TRANSITIONS
