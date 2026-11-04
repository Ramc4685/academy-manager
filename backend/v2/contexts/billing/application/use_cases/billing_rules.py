"""Settings -> Billing rules: one read and one audited write.

Spec: ``docs/superpowers/specs/2026-09-07-billing-rules-design.md``.

Every number that decides when money moves is assembled here into one view,
each row marked ``editable`` or fixed. **Fixed rows are derived from the
constants that govern the behaviour, never re-typed as literals** — the ladder
and charge hour from ``domain/dunning.py`` and the proration policy version
from ``domain/proration.py`` — so the page cannot drift away from the worker.
``tests/application/billing/test_billing_rules.py`` proves that by changing a
constant and watching the view change.

The editable rows live in three different stores (billing settings, the
academy fees subdocument, the parent self-service policy). Two of those belong
to other bounded contexts, so the collaborators arrive as structural
Protocols; ``composition/billing_rules.py`` supplies adapters over the real
use cases. Nothing here imports another context.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Final, Literal, Protocol

from pydantic import BaseModel

from backend.v2.contexts.billing.application.use_cases.billing_settings_admin import (
    BillingAuditAppender,
    SetInvoiceScheduleCommand,
)
from backend.v2.contexts.billing.domain.billing_audit import BillingAuditEntry
from backend.v2.contexts.billing.domain.dunning import (
    DUNNING_SCHEDULE_DAYS,
    FIRST_ATTEMPT_LOCAL_HOUR,
    MAX_DUNNING_ATTEMPTS,
)
from backend.v2.contexts.billing.domain.proration import BillingCalculationSnapshot
from backend.v2.shared.ids import new_ulid

log = logging.getLogger(__name__)

RuleUnit = Literal["day_of_month", "days", "cents"]

#: Inclusive bounds for every editable rule, checked before any store is
#: touched (spec SS4.2). The academy fees route has no bounds today — a
#: negative late fee is currently accepted — so these are added here and the
#: legacy route is left alone.
BILLING_RULE_BOUNDS: Final[Mapping[str, tuple[int, int]]] = {
    "billing_day": (1, 28),
    "invoice_due_days": (0, 60),
    "grace_days": (0, 60),
    "late_fee_cents": (0, 100_000),
    "cancellation_minimum_notice_days": (0, 90),
    "cancellation_fee_cents": (0, 100_000),
}

#: ``reminder_days`` is the one editable rule that is a LIST, not a number:
#: the owner's decision was "due+15 and due+20, both editable, empty = off"
#: (issue #774), and an empty list is the off switch. It therefore carries its
#: own per-entry bounds instead of a row in ``BILLING_RULE_BOUNDS``, which the
#: integer validate/diff/apply pipeline below iterates over.
REMINDER_DAYS_KEY: Final[str] = "reminder_days"
REMINDER_DAY_BOUNDS: Final[tuple[int, int]] = (1, 60)
MAX_REMINDER_DAYS: Final[int] = 4

#: ``cancellation_effective_timing`` is an enum, not a bounded number, so it
#: carries its own choices instead of a row in ``BILLING_RULE_BOUNDS``.
#: Settings overhaul Phase 3 PR 10: moved here from Self-service (now Family
#: policies), same pattern #1002 used for the cancellation fee.
CANCELLATION_TIMING_KEY: Final[str] = "cancellation_effective_timing"
CANCELLATION_TIMING_CHOICES: Final[tuple[str, ...]] = ("immediate", "end_of_period")

#: ``drop_default_outcome`` is also an enum row. Settings overhaul Phase 3
#: PR 10: moved here from the Holds card (``EnrollmentDeparturePolicy`` in the
#: enrollment context), same pattern used for the cancellation timing above.
DROP_DEFAULT_OUTCOME_KEY: Final[str] = "drop_default_outcome"
DROP_DEFAULT_OUTCOME_CHOICES: Final[tuple[str, ...]] = (
    "no_credit_mid_month",
    "credit_mid_month",
    "no_credit_end_of_period",
)

#: ``ach_discount`` is a compound row (on/off plus a percent), so it carries
#: its own key instead of a row in ``BILLING_RULE_BOUNDS``. Settings overhaul
#: Phase 4 PR 13. It edits ``billing_settings.ach_discount_enabled`` and
#: ``ach_discount_percent``; the ceiling ``max_ach_discount_percent`` is read
#: from the same document and is never writable from here.
ACH_DISCOUNT_KEY: Final[str] = "ach_discount"
ACH_DISCOUNT_HELPER: Final[str] = (
    "Autopay only. Applies to autopay bank payments, taken after any tuition discount. "
    "Checkout does not apply it."
)

#: Every editable rule, numeric ones first. ``test_billing_rules`` pins this
#: tuple to both the view's editable rows and the write command's fields, so a
#: rule can never be editable on the page and unwritable in the command.
EDITABLE_RULE_KEYS: Final[tuple[str, ...]] = (
    *BILLING_RULE_BOUNDS,
    REMINDER_DAYS_KEY,
    CANCELLATION_TIMING_KEY,
    DROP_DEFAULT_OUTCOME_KEY,
    ACH_DISCOUNT_KEY,
)


# --- Ports -------------------------------------------------------------


class InvoiceScheduleLike(Protocol):
    billing_day: int
    invoice_due_days: int


class InvoiceScheduleReader(Protocol):
    async def execute(self) -> InvoiceScheduleLike: ...


class InvoiceScheduleWriter(Protocol):
    async def execute(self, cmd: SetInvoiceScheduleCommand) -> InvoiceScheduleLike: ...


class AcademyFeesLike(Protocol):
    """Read-only view of the two fee fields this panel owns.

    ``late_fee_effective_from`` is read with ``getattr`` by the late-fee pass
    rather than declared here, so older readers and test doubles still fit.

    Declared as properties rather than attributes because the identity use
    cases return a *frozen* dataclass, and a frozen dataclass cannot satisfy a
    protocol whose members are mutable attributes.
    """

    @property
    def late_fee_cents(self) -> int | None: ...

    @property
    def grace_days(self) -> int | None: ...


class AcademyFeesReader(Protocol):
    async def execute(self, academy_id: str) -> AcademyFeesLike: ...


class AcademyFeesWriter(Protocol):
    async def execute(self, academy_id: str, fields: dict[str, Any]) -> AcademyFeesLike: ...


class CancellationPolicyLike(Protocol):
    cancellation_minimum_notice_days: int
    cancellation_fee_cents: int
    cancellation_effective_timing: str


class CancellationPolicyReader(Protocol):
    async def execute(self) -> CancellationPolicyLike: ...


class CancellationPolicyWriter(Protocol):
    """Narrow port over ``UpdateSelfServicePolicy``.

    The self-service policy has six fields and lives in the enrollment
    context; the billing-rules panel owns two of them. The write is partial:
    ``None`` leaves that field as stored, and the adapter in
    ``composition/billing_rules.py`` never touches the other four, so a save
    here cannot put back a value the Self-service panel just wrote.
    """

    async def execute(
        self,
        *,
        cancellation_minimum_notice_days: int | None = None,
        cancellation_fee_cents: int | None = None,
        cancellation_effective_timing: str | None = None,
    ) -> CancellationPolicyLike: ...


class DropDefaultOutcomeLike(Protocol):
    drop_default_outcome: str


class DropDefaultOutcomeReader(Protocol):
    async def execute(self) -> DropDefaultOutcomeLike: ...


class DropDefaultOutcomeWriter(Protocol):
    """Narrow port over ``UpdateEnrollmentDeparturePolicy``.

    ``EnrollmentDeparturePolicy`` has four fields; the Holds card owns three
    of them (``composition/billing_rules.py`` wires the adapter that sends
    only ``drop_default_outcome``, ``None`` for the rest, which the use case
    leaves untouched — see its docstring).
    """

    async def execute(
        self, *, drop_default_outcome: str | None = None
    ) -> DropDefaultOutcomeLike: ...


class AchDiscountLike(Protocol):
    @property
    def ach_discount_enabled(self) -> bool: ...

    @property
    def ach_discount_percent(self) -> float: ...

    @property
    def max_ach_discount_percent(self) -> float: ...


class AchDiscountReader(Protocol):
    async def execute(self) -> AchDiscountLike: ...


class AchDiscountWriter(Protocol):
    """Narrow port over the billing-settings store.

    Writes ONLY the two academy-editable ACH fields. The ceiling
    (``max_ach_discount_percent``) is not a parameter here and the settings
    repository never persists it from a tenant write.
    """

    async def execute(self, *, enabled: bool, percent: float) -> AchDiscountLike: ...


# --- View --------------------------------------------------------------


class BillingRuleRow(BaseModel):
    model_config = {"frozen": True}

    key: str
    label: str
    editable: bool
    #: Editable rows only: the stored number, in the row's ``unit``.
    value: int | None = None
    #: ``reminder_days`` only: the stored day offsets. Empty means "off".
    values: tuple[int, ...] | None = None
    unit: RuleUnit | None = None
    min_value: int | None = None
    max_value: int | None = None
    #: ``cancellation_effective_timing`` only: the stored enum value and its
    #: allowed choices.
    choice: str | None = None
    choices: tuple[str, ...] | None = None
    #: ``ach_discount`` only: on/off, the stored percent and its ceiling.
    enabled: bool | None = None
    percent: float | None = None
    max_percent: float | None = None
    #: Fixed rows only: the stated value, rendered as muted text.
    display: str | None = None
    #: One line saying where the behaviour comes from.
    detail: str | None = None


class BillingRuleGroup(BaseModel):
    model_config = {"frozen": True}

    key: str
    title: str
    #: Shared caveat rendered ABOVE the rows (spec SS5).
    note: str | None = None
    rows: tuple[BillingRuleRow, ...]


class BillingRulesView(BaseModel):
    model_config = {"frozen": True}

    groups: tuple[BillingRuleGroup, ...]

    def row(self, key: str) -> BillingRuleRow:
        for group in self.groups:
            for row in group.rows:
                if row.key == key:
                    return row
        raise KeyError(key)

    @property
    def editable_keys(self) -> tuple[str, ...]:
        return tuple(row.key for group in self.groups for row in group.rows if row.editable)


#: The late-fee pass has run hourly on the dunning tick since #803
#: (``apply_late_fees.py``). This note used to say "Not applied automatically
#: yet", which told owners a live money setting was inert (money audit X4).
LATE_FEE_NOTE: Final[str] = (
    "Applied automatically. Every hour, each open invoice whose grace period has ended "
    "gets the late fee once. Autopay invoices still in their retry schedule wait until "
    "the retries finish. Turning a fee on only affects invoices whose grace period ends "
    "on or after that day; invoices already overdue are not charged."
)


def _editable(key: str, label: str, value: int | None, unit: RuleUnit) -> BillingRuleRow:
    low, high = BILLING_RULE_BOUNDS[key]
    return BillingRuleRow(
        key=key,
        label=label,
        editable=True,
        value=value,
        unit=unit,
        min_value=low,
        max_value=high,
    )


def _reminder_days(schedule: InvoiceScheduleLike) -> tuple[int, ...]:
    """Stored reminder offsets, tolerating a schedule reader that predates them.

    ``getattr`` rather than a protocol member on purpose: the invoice-schedule
    reader is also satisfied by older adapters and test doubles that only know
    ``billing_day``/``invoice_due_days``, and a missing attribute must read as
    "no reminders configured", never crash the whole settings page.
    """
    raw = getattr(schedule, "reminder_days", None)
    if not raw:
        return ()
    return tuple(sorted({int(day) for day in raw}))


def charge_hour_sentence() -> str:
    """Charge-time sentence, e.g. "09:00 academy time on the due date"."""
    return f"{FIRST_ATTEMPT_LOCAL_HOUR:02d}:00 academy time on the due date"


def retry_schedule_sentence() -> str:
    """Retry sentence, e.g. "same day, then 3, 5 and 7 days later, ...".

    Derived from ``DUNNING_SCHEDULE_DAYS`` so an edit to the ladder changes
    this page in the same commit.
    """
    days = list(DUNNING_SCHEDULE_DAYS)
    if not days:
        return "no automatic retries"
    first = "same day" if days[0] == 0 else f"{days[0]} days later"
    later = days[1:]
    if not later:
        return f"{first}, then autopay switches off"
    if len(later) == 1:
        tail = str(later[0])
    else:
        tail = f"{', '.join(str(day) for day in later[:-1])} and {later[-1]}"
    return f"{first}, then {tail} days later, then autopay switches off"


def proration_policy_version() -> str:
    """The proration policy version, read off the snapshot model's default."""
    default = BillingCalculationSnapshot.model_fields["policy_version"].default
    return str(default)


class BuildBillingRulesView:
    """Assemble every billing rule — editable and fixed — into one view."""

    def __init__(
        self,
        *,
        schedule: InvoiceScheduleReader,
        fees: AcademyFeesReader,
        cancellation: CancellationPolicyReader,
        drop_outcome: DropDefaultOutcomeReader,
        ach: AchDiscountReader,
    ) -> None:
        self._schedule = schedule
        self._fees = fees
        self._cancellation = cancellation
        self._drop_outcome = drop_outcome
        self._ach = ach

    async def execute(self, academy_id: str) -> BillingRulesView:
        schedule = await self._schedule.execute()
        fees = await self._fees.execute(academy_id)
        policy = await self._cancellation.execute()
        departure = await self._drop_outcome.execute()
        ach = await self._ach.execute()
        return BillingRulesView(
            groups=(
                BillingRuleGroup(
                    key="monthly_invoicing",
                    title="Monthly invoicing",
                    rows=(
                        _editable(
                            "billing_day",
                            "Invoice day of month",
                            schedule.billing_day,
                            "day_of_month",
                        ),
                        _editable(
                            "invoice_due_days",
                            "Days until due",
                            schedule.invoice_due_days,
                            "days",
                        ),
                        BillingRuleRow(
                            key="autopay_charge_time",
                            label="Autopay charge time",
                            editable=False,
                            display=charge_hour_sentence(),
                            detail=(
                                "The dunning worker prepares the first attempt from this "
                                "hour in the academy's timezone."
                            ),
                        ),
                        BillingRuleRow(
                            key="retry_schedule",
                            label="Retry schedule after a failed charge",
                            editable=False,
                            display=retry_schedule_sentence(),
                            detail=(
                                f"{MAX_DUNNING_ATTEMPTS} attempts in total, then the "
                                "enrollment's autopay is switched off."
                            ),
                        ),
                    ),
                ),
                BillingRuleGroup(
                    key="late_payments",
                    title="Late payments",
                    note=LATE_FEE_NOTE,
                    rows=(
                        _editable("grace_days", "Grace days after due", fees.grace_days, "days"),
                        _editable("late_fee_cents", "Late fee", fees.late_fee_cents, "cents"),
                        BillingRuleRow(
                            key=ACH_DISCOUNT_KEY,
                            label="Bank (ACH) discount",
                            editable=True,
                            enabled=bool(ach.ach_discount_enabled),
                            percent=float(ach.ach_discount_percent),
                            max_percent=float(ach.max_ach_discount_percent),
                            detail=ACH_DISCOUNT_HELPER,
                        ),
                    ),
                ),
                BillingRuleGroup(
                    key="leaving_and_pausing",
                    title="Leaving and pausing",
                    rows=(
                        BillingRuleRow(
                            key="cancel_mid_month",
                            label="Cancel mid-month",
                            editable=False,
                            display="Full month owed, no refund",
                            detail=(
                                "Self-cancellation keeps the cancellation month payable "
                                "and voids later invoices."
                            ),
                        ),
                        BillingRuleRow(
                            key="join_mid_month",
                            label="Join mid-month",
                            editable=False,
                            display="Prorated from the start date",
                            detail=f"Proration policy {proration_policy_version()}.",
                        ),
                        BillingRuleRow(
                            key="paused_months",
                            label="Paused months",
                            editable=False,
                            display="Not invoiced",
                            detail="The monthly generator skips paused enrollments.",
                        ),
                        _editable(
                            "cancellation_minimum_notice_days",
                            "Cancellation notice",
                            policy.cancellation_minimum_notice_days,
                            "days",
                        ),
                        _editable(
                            "cancellation_fee_cents",
                            "Late-cancellation fee",
                            policy.cancellation_fee_cents,
                            "cents",
                        ),
                        BillingRuleRow(
                            key=CANCELLATION_TIMING_KEY,
                            label="When a cancellation takes effect",
                            editable=True,
                            choice=policy.cancellation_effective_timing,
                            choices=CANCELLATION_TIMING_CHOICES,
                        ),
                        BillingRuleRow(
                            key=DROP_DEFAULT_OUTCOME_KEY,
                            label="Default when staff drop a student",
                            editable=True,
                            choice=departure.drop_default_outcome,
                            choices=DROP_DEFAULT_OUTCOME_CHOICES,
                            detail=(
                                "Used when staff drop a student without picking an outcome "
                                "for that drop."
                            ),
                        ),
                    ),
                ),
                BillingRuleGroup(
                    key="parent_messages",
                    title="Parent messages",
                    rows=(
                        BillingRuleRow(
                            key="autopay_notice",
                            label="Autopay notice on invoice day",
                            editable=False,
                            display="On",
                            detail="Autopay parents get a notice instead of the invoice email.",
                        ),
                        BillingRuleRow(
                            key="charge_receipt",
                            label="Receipt after a successful charge",
                            editable=False,
                            display="On",
                        ),
                        BillingRuleRow(
                            key="failure_notice",
                            label="Payment failure notice",
                            editable=False,
                            display="Sent by the dunning ladder",
                        ),
                        BillingRuleRow(
                            key=REMINDER_DAYS_KEY,
                            label="Past-due reminder days",
                            editable=True,
                            values=_reminder_days(schedule),
                            unit="days",
                            min_value=REMINDER_DAY_BOUNDS[0],
                            max_value=REMINDER_DAY_BOUNDS[1],
                            detail=(
                                "Days after the due date the reminder job emails the "
                                "parent. Leave empty to send none."
                            ),
                        ),
                        BillingRuleRow(
                            key="manual_payer_reminders",
                            label="Extra reminders to manual payers",
                            editable=False,
                            display="Sent by hand from Payments, on top of the schedule above.",
                        ),
                    ),
                ),
            )
        )


# --- Write -------------------------------------------------------------


def _validate_reminder_days(raw: list[int] | None) -> tuple[int, ...] | None:
    """Normalise the requested reminder offsets, or raise naming the field.

    ``None`` in, ``None`` out: the field was not part of this request. An empty
    list normalises to an empty tuple — a real value meaning "send none".
    """
    if raw is None:
        return None
    low, high = REMINDER_DAY_BOUNDS
    for day in raw:
        if not isinstance(day, int) or isinstance(day, bool):
            raise BillingRulesValidationError(
                REMINDER_DAYS_KEY, "reminder_days must be whole numbers of days"
            )
        if day < low or day > high:
            raise BillingRulesValidationError(
                REMINDER_DAYS_KEY, f"each reminder day must be between {low} and {high}"
            )
    days = tuple(sorted(set(raw)))
    if len(days) > MAX_REMINDER_DAYS:
        raise BillingRulesValidationError(
            REMINDER_DAYS_KEY, f"at most {MAX_REMINDER_DAYS} reminder days are allowed"
        )
    return days


def _validate_ach_discount(
    change: AchDiscountChange | None, current: dict[str, Any], ceiling: float
) -> dict[str, Any] | None:
    """The full ACH state after ``change``, or raise naming the field.

    ``0 < percent <= ceiling`` whenever a percent is sent or the discount is
    on. The ceiling is the stored ``max_ach_discount_percent`` (code default
    when unset); a tenant can never move it. Percent is kept to two decimals.
    """
    if change is None:
        return None
    enabled = current["enabled"] if change.enabled is None else change.enabled
    percent = current["percent"]
    if change.percent is not None:
        raw = change.percent
        if isinstance(raw, bool) or raw != raw or raw in (float("inf"), float("-inf")):
            raise BillingRulesValidationError(
                "ach_discount_percent", "ach_discount_percent must be a number"
            )
        percent = round(float(raw), 2)
        if percent <= 0 or percent > ceiling:
            raise BillingRulesValidationError(
                "ach_discount_percent",
                f"ach_discount_percent must be more than 0 and at most {ceiling:g}",
            )
    if enabled and (percent <= 0 or percent > ceiling):
        raise BillingRulesValidationError(
            "ach_discount_percent",
            f"ach_discount_percent must be more than 0 and at most {ceiling:g} to turn it on",
        )
    return {"enabled": bool(enabled), "percent": float(percent)}


class BillingRulesValidationError(ValueError):
    """A rule value is outside its bound. Carries the offending field."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


class BillingRulesPartialWriteError(RuntimeError):
    """A later store write failed after earlier ones landed.

    Carries the fields that actually changed so the route can tell the owner
    what was saved, and so the audit entry never claims more than that.
    """

    def __init__(self, applied_fields: tuple[str, ...], cause: BaseException) -> None:
        super().__init__(f"billing rules partially applied: {', '.join(applied_fields) or 'none'}")
        self.applied_fields = applied_fields
        self.__cause__ = cause


class AchDiscountChange(BaseModel):
    model_config = {"frozen": True}

    enabled: bool | None = None
    percent: float | None = None


class UpdateBillingRulesCommand(BaseModel):
    model_config = {"frozen": True}

    #: Every field optional; only the ones present are written. Bounds are
    #: checked by the use case (not by Field constraints) so one code path
    #: produces the 422 and names the offending field.
    billing_day: int | None = None
    invoice_due_days: int | None = None
    grace_days: int | None = None
    late_fee_cents: int | None = None
    cancellation_minimum_notice_days: int | None = None
    cancellation_fee_cents: int | None = None
    #: Issue #774. ``None`` means "leave alone"; ``[]`` means "turn reminders
    #: off", which is a real change and must not be confused with the former.
    reminder_days: list[int] | None = None
    #: Settings overhaul Phase 3 PR 10, moved from Self-service.
    cancellation_effective_timing: Literal["immediate", "end_of_period"] | None = None
    #: Settings overhaul Phase 3 PR 10, moved from the Holds card.
    drop_default_outcome: (
        Literal["no_credit_mid_month", "credit_mid_month", "no_credit_end_of_period"] | None
    ) = None
    #: Settings overhaul Phase 4 PR 13. Present = write; either half may be
    #: omitted to keep its stored value.
    ach_discount: AchDiscountChange | None = None
    actor_id: str
    reason: str | None = None

    def requested(self) -> dict[str, int]:
        """The numeric rules present in this request. ``reminder_days`` is a
        list and is validated and diffed on its own path."""
        return {
            key: value for key in BILLING_RULE_BOUNDS if (value := getattr(self, key)) is not None
        }


class BillingRulesWriteResult(BaseModel):
    model_config = {"frozen": True}

    changed_fields: tuple[str, ...]
    #: False when the writes landed but the audit entry could not be appended.
    #: The change is real either way; this says whether it left a trail.
    audited: bool = True


class UpdateBillingRules:
    """Validate every field, then apply each to its existing store.

    Order of operations, spec SS4.1/SS4.2:

    1. validate every requested field against ``BILLING_RULE_BOUNDS`` — a bad
       late fee must not leave a saved billing day behind it;
    2. read current values and diff, so a no-op is a no-op;
    3. apply invoice schedule, then academy fees, then the cancellation
       policy, each through its own existing use case;
    4. append exactly one ``billing_rules_changed`` audit entry describing the
       fields that actually changed.

    The audit is written *after* the stores here, unlike
    ``SetInvoiceScheduleSettings``, because this write spans three stores and
    the log must never claim a change that did not land. A partial failure
    still writes the entry for what did land, then raises.
    """

    def __init__(
        self,
        *,
        schedule_reader: InvoiceScheduleReader,
        schedule_writer: InvoiceScheduleWriter,
        fees_reader: AcademyFeesReader,
        fees_writer: AcademyFeesWriter,
        cancellation_reader: CancellationPolicyReader,
        cancellation_writer: CancellationPolicyWriter,
        drop_outcome_reader: DropDefaultOutcomeReader,
        drop_outcome_writer: DropDefaultOutcomeWriter,
        ach_reader: AchDiscountReader,
        ach_writer: AchDiscountWriter,
        audit: BillingAuditAppender | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._schedule_reader = schedule_reader
        self._schedule_writer = schedule_writer
        self._fees_reader = fees_reader
        self._fees_writer = fees_writer
        self._cancellation_reader = cancellation_reader
        self._cancellation_writer = cancellation_writer
        self._drop_outcome_reader = drop_outcome_reader
        self._drop_outcome_writer = drop_outcome_writer
        self._ach_reader = ach_reader
        self._ach_writer = ach_writer
        self._audit = audit
        self._now = clock

    async def execute(
        self, academy_id: str, cmd: UpdateBillingRulesCommand
    ) -> BillingRulesWriteResult:
        requested = cmd.requested()
        for field, value in requested.items():
            low, high = BILLING_RULE_BOUNDS[field]
            if value < low or value > high:
                raise BillingRulesValidationError(
                    field, f"{field} must be between {low} and {high}"
                )
        reminder_days = _validate_reminder_days(cmd.reminder_days)
        timing = cmd.cancellation_effective_timing
        drop_outcome = cmd.drop_default_outcome
        ach_change = cmd.ach_discount
        if ach_change is not None and ach_change.enabled is None and ach_change.percent is None:
            ach_change = None
        if (
            not requested
            and reminder_days is None
            and timing is None
            and drop_outcome is None
            and ach_change is None
        ):
            return BillingRulesWriteResult(changed_fields=())

        schedule = await self._schedule_reader.execute()
        fees = await self._fees_reader.execute(academy_id)
        policy = await self._cancellation_reader.execute()
        departure = await self._drop_outcome_reader.execute()
        ach_now = await self._ach_reader.execute()
        before_ach = {
            "enabled": bool(ach_now.ach_discount_enabled),
            "percent": float(ach_now.ach_discount_percent),
        }
        ach_after = _validate_ach_discount(
            ach_change, before_ach, float(ach_now.max_ach_discount_percent)
        )
        before: dict[str, Any] = {
            "billing_day": schedule.billing_day,
            "invoice_due_days": schedule.invoice_due_days,
            "grace_days": fees.grace_days,
            "late_fee_cents": fees.late_fee_cents,
            "cancellation_minimum_notice_days": policy.cancellation_minimum_notice_days,
            "cancellation_fee_cents": policy.cancellation_fee_cents,
            REMINDER_DAYS_KEY: _reminder_days(schedule),
            CANCELLATION_TIMING_KEY: policy.cancellation_effective_timing,
            DROP_DEFAULT_OUTCOME_KEY: departure.drop_default_outcome,
            ACH_DISCOUNT_KEY: before_ach,
        }
        changed: dict[str, Any] = {
            field: value for field, value in requested.items() if before[field] != value
        }
        if reminder_days is not None and before[REMINDER_DAYS_KEY] != reminder_days:
            changed[REMINDER_DAYS_KEY] = reminder_days
        if timing is not None and before[CANCELLATION_TIMING_KEY] != timing:
            changed[CANCELLATION_TIMING_KEY] = timing
        if drop_outcome is not None and before[DROP_DEFAULT_OUTCOME_KEY] != drop_outcome:
            changed[DROP_DEFAULT_OUTCOME_KEY] = drop_outcome
        if ach_after is not None and ach_after != before_ach:
            changed[ACH_DISCOUNT_KEY] = ach_after
        if not changed:
            return BillingRulesWriteResult(changed_fields=())

        applied: list[str] = []
        try:
            await self._apply(academy_id, before, changed, applied, cmd.actor_id, cmd.reason)
        except Exception as exc:  # re-raised below, after the audit lands
            await self._audit_best_effort(cmd, academy_id, before, tuple(applied), changed)
            raise BillingRulesPartialWriteError(tuple(applied), exc) from exc

        # The writes have landed. An audit failure from here must not be
        # reported as "nothing was saved": the owner would retry, the retry
        # would diff clean and write no audit at all, and a money-timing change
        # would be live with no trail. Report what was saved and log loudly.
        audited = await self._audit_best_effort(cmd, academy_id, before, tuple(applied), changed)
        return BillingRulesWriteResult(changed_fields=tuple(applied), audited=audited)

    async def _audit_best_effort(
        self,
        cmd: UpdateBillingRulesCommand,
        academy_id: str,
        before: dict[str, Any],
        applied: tuple[str, ...],
        changed: dict[str, Any],
    ) -> bool:
        """Append the audit entry; never let its failure mask what was written."""
        try:
            await self._append_audit(cmd, academy_id, before, applied, changed)
        except Exception:
            log.error(
                "billing_rules_audit_failed",
                exc_info=True,
                extra={"academy_id": academy_id, "fields": list(applied)},
            )
            return False
        return True

    async def _apply(
        self,
        academy_id: str,
        before: dict[str, Any],
        changed: dict[str, Any],
        applied: list[str],
        actor_id: str,
        reason: str | None,
    ) -> None:
        schedule_fields = [
            f for f in ("billing_day", "invoice_due_days", REMINDER_DAYS_KEY) if f in changed
        ]
        if schedule_fields:
            await self._schedule_writer.execute(
                SetInvoiceScheduleCommand(
                    billing_day=changed.get("billing_day", before["billing_day"]),
                    invoice_due_days=changed.get("invoice_due_days", before["invoice_due_days"]),
                    reminder_days=changed.get(REMINDER_DAYS_KEY, before[REMINDER_DAYS_KEY]),
                    # The real owner, not a placeholder: anyone querying
                    # `invoice_schedule_changed` for "who moved invoice day"
                    # must get the same answer as the billing_rules_changed
                    # entry written beside it.
                    actor_id=actor_id,
                    reason=reason or "Settings -> Billing rules",
                )
            )
            applied.extend(schedule_fields)

        fee_fields = [f for f in ("grace_days", "late_fee_cents") if f in changed]
        if fee_fields:
            await self._fees_writer.execute(
                academy_id, {field: changed[field] for field in fee_fields}
            )
            applied.extend(fee_fields)

        policy_fields = [
            f
            for f in (
                "cancellation_minimum_notice_days",
                "cancellation_fee_cents",
                CANCELLATION_TIMING_KEY,
            )
            if f in changed
        ]
        if policy_fields:
            # Only the changed field(s); `None` leaves the others as stored.
            await self._cancellation_writer.execute(
                cancellation_minimum_notice_days=changed.get("cancellation_minimum_notice_days"),
                cancellation_fee_cents=changed.get("cancellation_fee_cents"),
                cancellation_effective_timing=changed.get(CANCELLATION_TIMING_KEY),
            )
            applied.extend(policy_fields)

        if DROP_DEFAULT_OUTCOME_KEY in changed:
            await self._drop_outcome_writer.execute(
                drop_default_outcome=changed[DROP_DEFAULT_OUTCOME_KEY]
            )
            applied.append(DROP_DEFAULT_OUTCOME_KEY)

        if ACH_DISCOUNT_KEY in changed:
            ach = changed[ACH_DISCOUNT_KEY]
            await self._ach_writer.execute(enabled=ach["enabled"], percent=ach["percent"])
            applied.append(ACH_DISCOUNT_KEY)

    async def _append_audit(
        self,
        cmd: UpdateBillingRulesCommand,
        academy_id: str,
        before: dict[str, Any],
        applied: tuple[str, ...],
        changed: dict[str, Any],
    ) -> None:
        if self._audit is None or not applied:
            return
        await self._audit.append(
            BillingAuditEntry(
                audit_id=f"baud-{new_ulid()}",
                academy_id=academy_id,
                action="billing_rules_changed",
                actor_id=cmd.actor_id,
                at=self._now(),
                reason=cmd.reason,
                before={field: before[field] for field in applied},
                after={field: changed[field] for field in applied},
            )
        )
