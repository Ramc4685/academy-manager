"""Dunning retry ladder for app-owned autopay collection."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from backend.v2.contexts.billing.domain.ach_returns import (
    ACH_MAX_ATTEMPTS,
    ACH_RETRY_DELAY_DAYS,
    ach_failure_disposition,
    is_bank_debit_failure,
)

DUNNING_SCHEDULE_DAYS = (0, 3, 5, 7)
MAX_DUNNING_ATTEMPTS = len(DUNNING_SCHEDULE_DAYS)

#: Local hour (academy timezone) before which no NEW ladder is prepared on its
#: due date, so the first autopay attempt lands in the morning of the due date
#: instead of 00:00 UTC — 7pm the evening before in Chicago (#651). It lives
#: here, beside the ladder it belongs to, so the application layer can read the
#: rule without importing the Mongo repository that obeys it.
FIRST_ATTEMPT_LOCAL_HOUR = 9

#: Stripe API or network error: we never reached the card or bank (A4-3).
STRIPE_UNAVAILABLE = "stripe_unavailable"

#: Technical parks retry every tick. Once a ladder has been parked for these alone
#: for TECHNICAL_PARK_CAP, it parks as TECHNICAL_FAILURE_CAPPED instead, which is
#: rechecked once a day rather than hourly: the failing call stops hitting Stripe
#: every hour, the admin and the alert take over, and a paid or voided invoice
#: stands down on the next daily check (A7-6).
TECHNICAL_PARK_REASONS = frozenset(
    {"charge_technical_failure", "attempt_indeterminate", STRIPE_UNAVAILABLE}
)
TECHNICAL_PARK_CAP = timedelta(hours=24)
TECHNICAL_FAILURE_CAPPED = "technical_failure_capped"

#: Park reasons that mean "we could not ask the bank" because of something on our
#: side. A ladder parked for one of these is listed for the admin and counted by
#: the ops digest; settling ACH debits, open checkouts and paused enrollments are
#: ordinary states and stay quiet (L1 A7-1).
PARK_REASONS_NEEDING_ATTENTION = frozenset(
    {
        "charge_technical_failure",
        "attempt_indeterminate",
        "connected_account_not_ready",
        "stripe_not_configured",
        STRIPE_UNAVAILABLE,
        TECHNICAL_FAILURE_CAPPED,
    }
)

#: The subset the academy fixes itself by finishing Stripe setup, so the owner
#: dashboard words them as "finish Stripe setup", not a fault on our side.
PARK_REASONS_NEEDING_STRIPE_SETUP = frozenset(
    {"connected_account_not_ready", "stripe_not_configured"}
)

#: Attempt failure codes for a bank return or dispute the ledger did not reverse
#: (partial, or nothing reversible): the owner reconciles these by hand.
UNSUPPORTED_PARTIAL_RETURN = "unsupported_partial_ach_return"
UNRECONCILED_RETURN = "unreconciled_payment_return"
RETURN_CODES_NEEDING_MANUAL_REVIEW = frozenset({UNSUPPORTED_PARTIAL_RETURN, UNRECONCILED_RETURN})

#: No saved card or bank: the parent has to act, not us. Emailed to the parent
#: once and shown in the Payments buckets, never an ops-digest fault (owner 2026-11-15).
NO_SAVED_PAYMENT_METHOD = "no_saved_payment_method"

DunningStatus = Literal["active", "processing", "resolved", "dunned", "suppressed"]
AutopayDisableStatus = Literal["pending", "succeeded", "failed", "not_required"]


class DunningState(BaseModel):
    model_config = {"frozen": True}

    academy_id: str
    invoice_id: str
    parent_id: str
    enrollment_id: str | None = None
    status: DunningStatus = "active"
    attempt_count: int = Field(default=0, ge=0)
    processing_attempt_no: int | None = None
    processing_worker_id: str | None = None
    processing_started_at: datetime | None = None
    lease_expires_at: datetime | None = None
    first_attempt_at: datetime | None = None
    last_attempt_at: datetime | None = None
    next_attempt_at: datetime | None = None
    last_failure_code: str | None = None
    suppression_reason: str | None = None
    suppressed_at: datetime | None = None
    #: When this rung first parked; survives re-claims so "parked for a day" is
    #: measurable (each re-park overwrites suppressed_at).
    parked_since: datetime | None = None
    #: Start of the current unbroken run of TECHNICAL_PARK_REASONS parks; cleared
    #: by any other park or any recorded attempt.
    technical_parked_since: datetime | None = None
    #: Set on claim when the bank debit this rung was waiting on has come back
    #: failed: the worker records that failure instead of debiting again (A4-2).
    settling_failure_code: str | None = None
    #: The last failed rung was a bank debit, so a terminal ladder pauses autopay
    #: (re-link a bank) instead of disabling it.
    last_failure_was_bank_debit: bool = False
    #: The family charge this rung belongs to (L8). Stamped at claim on every
    #: member, so a stale-lease re-claim charges exactly the same group under the
    #: same PaymentIntent key. Kept after the attempt as a marker: the members'
    #: settle claims and their one notice find each other by it.
    charge_group_id: str | None = None
    notification_attempts: tuple[int, ...] = ()
    last_notification_at: datetime | None = None
    terminal_at: datetime | None = None
    resolved_at: datetime | None = None
    autopay_disable_status: AutopayDisableStatus | None = None
    autopay_disable_error: str | None = None
    autopay_disabled_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    def claim(
        self,
        *,
        attempt_no: int,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime | None = None,
        settling_failure_code: str | None = None,
        charge_group_id: str | None = None,
    ) -> DunningState:
        if self.status not in {"active", "processing"}:
            raise ValueError("only active or stale-processing dunning states can be claimed")
        if attempt_no != self.attempt_count + 1:
            raise ValueError("attempt_no must be the next retry attempt")
        if attempt_no > MAX_DUNNING_ATTEMPTS:
            raise ValueError("attempt_no exceeds dunning ladder")
        return self.model_copy(
            update={
                "status": "processing",
                "processing_attempt_no": attempt_no,
                "processing_worker_id": worker_id,
                "processing_started_at": now,
                "lease_expires_at": lease_expires_at,
                "settling_failure_code": settling_failure_code,
                "charge_group_id": charge_group_id,
                "suppression_reason": None,
                "suppressed_at": None,
                "updated_at": now,
            }
        )

    def release(self, *, next_attempt_at: datetime | None, now: datetime) -> DunningState:
        if self.status != "processing":
            raise ValueError("only processing dunning states can be released")
        return self.model_copy(
            update={
                "status": "active",
                "processing_attempt_no": None,
                "processing_worker_id": None,
                "processing_started_at": None,
                "settling_failure_code": None,
                "lease_expires_at": None,
                "next_attempt_at": next_attempt_at,
                "updated_at": now,
            }
        )

    def suppress(self, *, reason: str, now: datetime) -> DunningState:
        return self.model_copy(
            update={
                "status": "suppressed",
                "processing_attempt_no": None,
                "processing_worker_id": None,
                "processing_started_at": None,
                "settling_failure_code": None,
                "lease_expires_at": None,
                "next_attempt_at": None,
                "suppression_reason": reason,
                "suppressed_at": now,
                "parked_since": None,
                "updated_at": now,
            }
        )

    def park(self, *, reason: str, now: datetime) -> DunningState:
        if self.status != "processing":
            raise ValueError("only processing dunning states can be parked")
        technical_since = None
        if reason in TECHNICAL_PARK_REASONS:
            technical_since = self.technical_parked_since or now
            if now - technical_since >= TECHNICAL_PARK_CAP:
                reason = TECHNICAL_FAILURE_CAPPED
        return self.model_copy(
            update={
                "status": "active",
                "processing_attempt_no": None,
                "processing_worker_id": None,
                "processing_started_at": None,
                "settling_failure_code": None,
                "lease_expires_at": None,
                "next_attempt_at": None,
                "suppression_reason": reason,
                "suppressed_at": now,
                "parked_since": self.parked_since or now,
                "technical_parked_since": technical_since,
                "updated_at": now,
            }
        )

    def resolve(self, *, now: datetime) -> DunningState:
        return self.model_copy(
            update={
                "status": "resolved",
                "processing_attempt_no": None,
                "processing_worker_id": None,
                "processing_started_at": None,
                "settling_failure_code": None,
                "lease_expires_at": None,
                "next_attempt_at": None,
                "parked_since": None,
                "resolved_at": now,
                "updated_at": now,
            }
        )

    def mark_notification_sent(self, *, attempt_no: int, now: datetime) -> DunningState:
        attempts = tuple(sorted({*self.notification_attempts, attempt_no}))
        return self.model_copy(
            update={
                "notification_attempts": attempts,
                "last_notification_at": now,
                "updated_at": now,
            }
        )


def open_initial_dunning_state(
    *,
    academy_id: str,
    invoice_id: str,
    parent_id: str,
    enrollment_id: str | None,
    due_at: datetime,
    now: datetime,
) -> DunningState:
    return DunningState(
        academy_id=academy_id,
        invoice_id=invoice_id,
        parent_id=parent_id,
        enrollment_id=enrollment_id,
        status="active",
        attempt_count=0,
        next_attempt_at=max_due_at(due_at=due_at, now=now),
        created_at=now,
        updated_at=now,
    )


def max_due_at(*, due_at: datetime, now: datetime) -> datetime:
    return due_at if due_at > now else now


def record_dunning_attempt_result(
    state: DunningState,
    *,
    succeeded: bool,
    failure_code: str | None,
    now: datetime,
) -> DunningState:
    if state.status != "processing" or state.processing_attempt_no is None:
        raise ValueError("dunning attempt result requires a claimed processing state")

    attempt_no = state.processing_attempt_no
    first_attempt_at = state.first_attempt_at or now
    # A failed bank debit (settled-then-failed, or refused at creation) runs the
    # bank ladder: only insufficient funds retries (counted from when the failure
    # is reported), anything else stops at once. A card decline keeps the card
    # schedule, even on a card that sat in "processing".
    bank_debit = not succeeded and is_bank_debit_failure(
        failure_code, settled=state.settling_failure_code is not None
    )
    bank_disposition = (ach_failure_disposition(failure_code) or "stop") if bank_debit else None
    if succeeded:
        return state.model_copy(
            update={
                "status": "resolved",
                "attempt_count": attempt_no,
                "processing_attempt_no": None,
                "processing_worker_id": None,
                "processing_started_at": None,
                "settling_failure_code": None,
                "lease_expires_at": None,
                "first_attempt_at": first_attempt_at,
                "technical_parked_since": None,
                "last_attempt_at": now,
                "parked_since": None,
                "next_attempt_at": None,
                "last_failure_code": None,
                "resolved_at": now,
                "updated_at": now,
            }
        )

    if (
        attempt_no >= MAX_DUNNING_ATTEMPTS
        or bank_disposition == "stop"
        or (bank_debit and attempt_no >= ACH_MAX_ATTEMPTS)
    ):
        return state.model_copy(
            update={
                "status": "dunned",
                "attempt_count": attempt_no,
                "processing_attempt_no": None,
                "processing_worker_id": None,
                "processing_started_at": None,
                "settling_failure_code": None,
                "lease_expires_at": None,
                "first_attempt_at": first_attempt_at,
                "technical_parked_since": None,
                "last_attempt_at": now,
                "parked_since": None,
                "next_attempt_at": None,
                "last_failure_code": failure_code,
                "last_failure_was_bank_debit": bank_debit,
                "terminal_at": now,
                "autopay_disable_status": "pending" if state.enrollment_id else "not_required",
                "autopay_disable_error": None,
                "updated_at": now,
            }
        )

    if bank_debit:
        next_due = now + timedelta(days=ACH_RETRY_DELAY_DAYS[attempt_no - 1])
    else:
        next_due = first_attempt_at + timedelta(days=DUNNING_SCHEDULE_DAYS[attempt_no])
    return state.model_copy(
        update={
            "status": "active",
            "attempt_count": attempt_no,
            "processing_attempt_no": None,
            "processing_worker_id": None,
            "processing_started_at": None,
            "settling_failure_code": None,
            "lease_expires_at": None,
            "first_attempt_at": first_attempt_at,
            "technical_parked_since": None,
            "last_attempt_at": now,
            "next_attempt_at": next_due,
            "parked_since": None,
            "last_failure_code": failure_code,
            "last_failure_was_bank_debit": bank_debit,
            "updated_at": now,
        }
    )
