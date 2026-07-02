from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.v2.contexts.billing.domain.dunning import (
    DUNNING_SCHEDULE_DAYS,
    DunningState,
    open_initial_dunning_state,
    record_dunning_attempt_result,
)

NOW = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)


def test_initial_dunning_state_is_due_immediately_on_day_zero() -> None:
    state = open_initial_dunning_state(
        academy_id="acad-1",
        invoice_id="inv-1",
        parent_id="parent-1",
        enrollment_id="enr-1",
        due_at=NOW,
        now=NOW,
    )

    assert DUNNING_SCHEDULE_DAYS == (0, 3, 5, 7)
    assert state.status == "active"
    assert state.attempt_count == 0
    assert state.next_attempt_at == NOW
    assert state.first_attempt_at is None


def test_failed_attempts_follow_day_0_3_5_7_ladder_from_first_attempt() -> None:
    state = open_initial_dunning_state(
        academy_id="acad-1",
        invoice_id="inv-1",
        parent_id="parent-1",
        enrollment_id="enr-1",
        due_at=NOW,
        now=NOW,
    )

    first = record_dunning_attempt_result(
        state.claim(attempt_no=1, worker_id="worker-1", now=NOW),
        succeeded=False,
        failure_code="insufficient_funds",
        now=NOW,
    )
    second_due = NOW + timedelta(days=3)
    assert first.status == "active"
    assert first.attempt_count == 1
    assert first.first_attempt_at == NOW
    assert first.next_attempt_at == second_due

    second = record_dunning_attempt_result(
        first.claim(attempt_no=2, worker_id="worker-1", now=second_due),
        succeeded=False,
        failure_code="insufficient_funds",
        now=second_due,
    )
    assert second.attempt_count == 2
    assert second.next_attempt_at == NOW + timedelta(days=5)

    third = record_dunning_attempt_result(
        second.claim(attempt_no=3, worker_id="worker-1", now=NOW + timedelta(days=5)),
        succeeded=False,
        failure_code="insufficient_funds",
        now=NOW + timedelta(days=5),
    )
    assert third.attempt_count == 3
    assert third.next_attempt_at == NOW + timedelta(days=7)


def test_fourth_failed_attempt_is_terminal_dunned() -> None:
    state = DunningState(
        academy_id="acad-1",
        invoice_id="inv-1",
        parent_id="parent-1",
        enrollment_id="enr-1",
        status="processing",
        attempt_count=3,
        processing_attempt_no=4,
        first_attempt_at=NOW,
        last_attempt_at=NOW + timedelta(days=5),
        next_attempt_at=NOW + timedelta(days=7),
        last_failure_code="insufficient_funds",
        notification_attempts=(1, 2, 3),
        created_at=NOW,
        updated_at=NOW + timedelta(days=7),
    )

    terminal = record_dunning_attempt_result(
        state,
        succeeded=False,
        failure_code="insufficient_funds",
        now=NOW + timedelta(days=7),
    )

    assert terminal.status == "dunned"
    assert terminal.attempt_count == 4
    assert terminal.next_attempt_at is None
    assert terminal.terminal_at == NOW + timedelta(days=7)


def test_success_resolves_dunning_without_more_retries() -> None:
    state = open_initial_dunning_state(
        academy_id="acad-1",
        invoice_id="inv-1",
        parent_id="parent-1",
        enrollment_id="enr-1",
        due_at=NOW,
        now=NOW,
    )

    resolved = record_dunning_attempt_result(
        state.claim(attempt_no=1, worker_id="worker-1", now=NOW),
        succeeded=True,
        failure_code=None,
        now=NOW,
    )

    assert resolved.status == "resolved"
    assert resolved.attempt_count == 1
    assert resolved.next_attempt_at is None
    assert resolved.resolved_at == NOW
