"""Response models for ``GET /admin/payments/collections``.

Field names follow spec §3 of
``docs/superpowers/specs/2026-09-05-payments-buckets-design.md`` exactly. The
read model hands back plain dicts; these models shape them and drop anything
the spec does not name (``extra="ignore"``).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

BucketKey = Literal[
    "failed_autopay",
    "past_due",
    "awaiting",
    "autopay_scheduled",
    "paused",
    "paid",
]

FamilyAction = Literal["send_reminder", "record_payment", "message", "skip_month", "resume"]


class _View(BaseModel):
    model_config = ConfigDict(extra="ignore")


class AdminCollectionsTotals(_View):
    owed_cents: int
    autopay_scheduled_cents: int
    autopay_scheduled_count: int
    needs_action_count: int
    collected_cents: int


class AdminCollectionsStudent(_View):
    student_id: str
    name: str
    session_title: str | None = None


class AdminCollectionsInvoice(_View):
    invoice_id: str
    invoice_number: str | None = None
    period: str
    status: str
    total_cents: int
    balance_due_cents: int
    due_date: str
    delivery_status: str | None = None


class AdminCollectionsAutopay(_View):
    status: str
    card_last4: str | None = None
    charge_on: str | None = None
    notice_sent_at: str | None = None


class AdminCollectionsFailure(_View):
    reason: str | None = None
    attempt_count: int
    max_attempts: int
    next_retry_on: str | None = None
    disabled: bool


class AdminCollectionsPause(_View):
    resume_on: str | None = None
    review_on: str | None = None
    session_title: str | None = None
    # Beyond spec §3: the Resume row action posts to
    # ``/admin/enrollments/{enrollment_id}/resume`` and the row names the
    # paused student, so the classifier's extra pause facts are kept.
    enrollment_id: str | None = None
    student_name: str | None = None


class AdminCollectionsPaid(_View):
    amount_cents: int
    method: str | None = None
    paid_at: str | None = None


class AdminCollectionsFamily(_View):
    parent_id: str
    # Nullable on purpose (spec §6, frontend ``parent_name: string | null``):
    # a parent with no ``users`` doc must not fail the whole response.
    parent_name: str | None = None
    parent_email: str | None = None
    students: list[AdminCollectionsStudent] = []
    invoices: list[AdminCollectionsInvoice] = []
    balance_cents: int
    leftover_balance_cents: int = 0
    autopay: AdminCollectionsAutopay | None = None
    failure: AdminCollectionsFailure | None = None
    pause: AdminCollectionsPause | None = None
    paid: AdminCollectionsPaid | None = None
    last_reminder_at: str | None = None
    actions: list[FamilyAction] = []


class AdminCollectionsBucket(_View):
    key: BucketKey
    count: int
    total_cents: int
    families: list[AdminCollectionsFamily] = []


class AdminCollectionsView(_View):
    period: str
    generated_at: str
    timezone: str
    totals: AdminCollectionsTotals
    buckets: list[AdminCollectionsBucket]
    unclassified: list[dict[str, Any]] | None = None
