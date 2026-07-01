"""Dunning retry ladder for app-owned autopay collection."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field

DUNNING_SCHEDULE_DAYS = (0, 3, 5, 7)
MAX_DUNNING_ATTEMPTS = len(DUNNING_SCHEDULE_DAYS)

DunningStatus = Literal["active", "processing", "resolved", "dunned"]


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
    first_attempt_at: datetime | None = None
    last_attempt_at: datetime | None = None
    next_attempt_at: datetime | None = None
    last_failure_code: str | None = None
    notification_attempts: tuple[int, ...] = ()
    last_notification_at: datetime | None = None
    terminal_at: datetime | None = None
    resolved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    def claim(self, *, attempt_no: int, worker_id: str, now: datetime) -> DunningState:
        if self.status != "active":
            raise ValueError("only active dunning states can be claimed")
        if attempt_no != self.attempt_count + 1:
            raise ValueError("attempt_no must be the next retry attempt")
        if attempt_no > MAX_DUNNING_ATTEMPTS:
            raise ValueError("attempt_no exceeds dunning ladder")
        return self.model_copy(
            update={
                "status": "processing",
                "processing_attempt_no": attempt_no,
                "processing_worker_id": worker_id,
                "updated_at": now,
            }
        )

    def release(self, *, next_attempt_at: datetime, now: datetime) -> DunningState:
        if self.status != "processing":
            raise ValueError("only processing dunning states can be released")
        return self.model_copy(
            update={
                "status": "active",
                "processing_attempt_no": None,
                "processing_worker_id": None,
                "next_attempt_at": next_attempt_at,
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
    if succeeded:
        return state.model_copy(
            update={
                "status": "resolved",
                "attempt_count": attempt_no,
                "processing_attempt_no": None,
                "processing_worker_id": None,
                "first_attempt_at": first_attempt_at,
                "last_attempt_at": now,
                "next_attempt_at": None,
                "last_failure_code": None,
                "resolved_at": now,
                "updated_at": now,
            }
        )

    if attempt_no >= MAX_DUNNING_ATTEMPTS:
        return state.model_copy(
            update={
                "status": "dunned",
                "attempt_count": attempt_no,
                "processing_attempt_no": None,
                "processing_worker_id": None,
                "first_attempt_at": first_attempt_at,
                "last_attempt_at": now,
                "next_attempt_at": None,
                "last_failure_code": failure_code,
                "terminal_at": now,
                "updated_at": now,
            }
        )

    next_due = first_attempt_at + timedelta(days=DUNNING_SCHEDULE_DAYS[attempt_no])
    return state.model_copy(
        update={
            "status": "active",
            "attempt_count": attempt_no,
            "processing_attempt_no": None,
            "processing_worker_id": None,
            "first_attempt_at": first_attempt_at,
            "last_attempt_at": now,
            "next_attempt_at": next_due,
            "last_failure_code": failure_code,
            "updated_at": now,
        }
    )
