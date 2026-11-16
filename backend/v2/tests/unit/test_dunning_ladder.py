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


def _settled_bank_failure(*, attempt_no: int, code: str) -> DunningState:
    return DunningState(
        academy_id="acad-1",
        invoice_id="inv-1",
        parent_id="parent-1",
        enrollment_id="enr-1",
        status="processing",
        attempt_count=attempt_no - 1,
        processing_attempt_no=attempt_no,
        first_attempt_at=NOW,
        settling_failure_code=code,
        created_at=NOW,
        updated_at=NOW,
    )


def test_bank_insufficient_funds_retries_three_then_seven_days_after_the_report() -> None:
    reported = NOW + timedelta(days=4)
    first = record_dunning_attempt_result(
        _settled_bank_failure(attempt_no=1, code="insufficient_funds"),
        succeeded=False,
        failure_code="insufficient_funds",
        now=reported,
    )
    assert first.status == "active"
    assert first.next_attempt_at == reported + timedelta(days=3)
    assert first.settling_failure_code is None

    second = record_dunning_attempt_result(
        _settled_bank_failure(attempt_no=2, code="R01"),
        succeeded=False,
        failure_code="R01",
        now=reported,
    )
    assert second.next_attempt_at == reported + timedelta(days=7)


def test_bank_insufficient_funds_stops_after_two_retries() -> None:
    third = record_dunning_attempt_result(
        _settled_bank_failure(attempt_no=3, code="insufficient_funds"),
        succeeded=False,
        failure_code="insufficient_funds",
        now=NOW,
    )
    assert third.status == "dunned"
    assert third.autopay_disable_status == "pending"


def test_closed_or_unknown_bank_failure_stops_on_the_first_attempt() -> None:
    for code in ("bank_account_closed", "debit_not_authorized", "some_new_code"):
        stopped = record_dunning_attempt_result(
            _settled_bank_failure(attempt_no=1, code=code),
            succeeded=False,
            failure_code=code,
            now=NOW,
        )
        assert stopped.status == "dunned", code
        assert stopped.last_failure_code == code


def test_card_insufficient_funds_keeps_the_card_ladder() -> None:
    state = _settled_bank_failure(attempt_no=1, code="x").model_copy(
        update={"settling_failure_code": None}
    )
    card = record_dunning_attempt_result(
        state, succeeded=False, failure_code="insufficient_funds", now=NOW
    )
    assert card.status == "active"
    assert card.next_attempt_at == NOW + timedelta(days=DUNNING_SCHEDULE_DAYS[1])


def _claimed(*, settling: str | None = None, parked: bool = False) -> DunningState:
    state = open_initial_dunning_state(
        academy_id="a",
        invoice_id="inv-1",
        parent_id="p",
        enrollment_id="e",
        due_at=NOW,
        now=NOW,
    )
    if parked:
        state = state.model_copy(update={"parked_since": NOW})
    return state.claim(attempt_no=1, worker_id="w", now=NOW, settling_failure_code=settling)


def test_bank_refused_at_creation_stops_on_the_bank_ladder() -> None:
    """L1 review: a 402 bank_account_unusable at creation is a bank failure, not
    the 4-attempt card ladder with card wording."""
    after = record_dunning_attempt_result(
        _claimed(), succeeded=False, failure_code="bank_account_unusable", now=NOW
    )
    assert after.status == "dunned"
    assert after.last_failure_was_bank_debit is True


def test_a_card_that_sat_in_processing_keeps_the_card_ladder() -> None:
    after = record_dunning_attempt_result(
        _claimed(settling="card_declined"), succeeded=False, failure_code="card_declined", now=NOW
    )
    assert after.status == "active"
    assert after.last_failure_was_bank_debit is False


def test_a_card_insufficient_funds_at_creation_is_not_a_bank_failure() -> None:
    after = record_dunning_attempt_result(
        _claimed(), succeeded=False, failure_code="insufficient_funds", now=NOW
    )
    assert after.last_failure_was_bank_debit is False


def test_a_failed_rung_that_retries_clears_parked_since() -> None:
    after = record_dunning_attempt_result(
        _claimed(parked=True), succeeded=False, failure_code="card_declined", now=NOW
    )
    assert after.status == "active"
    assert after.parked_since is None
