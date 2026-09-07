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

EDITABLE_RULE_KEYS: Final[tuple[str, ...]] = tuple(BILLING_RULE_BOUNDS)


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


class CancellationPolicyReader(Protocol):
    async def execute(self) -> CancellationPolicyLike: ...


class CancellationPolicyWriter(Protocol):
    """Narrow port over ``UpdateSelfServicePolicy``.

    The self-service policy has six fields and lives in the enrollment
    context; the billing-rules panel owns two of them. The adapter in
    ``composition/billing_rules.py`` carries the other four through unchanged,
    so both surfaces keep writing one stored value.
    """

    async def execute(
        self,
        *,
        cancellation_minimum_notice_days: int,
        cancellation_fee_cents: int,
    ) -> CancellationPolicyLike: ...


# --- View --------------------------------------------------------------


class BillingRuleRow(BaseModel):
    model_config = {"frozen": True}

    key: str
    label: str
    editable: bool
    #: Editable rows only: the stored number, in the row's ``unit``.
    value: int | None = None
    unit: RuleUnit | None = None
    min_value: int | None = None
    max_value: int | None = None
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


LATE_FEE_NOTE: Final[str] = (
    "Not applied automatically yet — these values are stored for when late fees ship."
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
    ) -> None:
        self._schedule = schedule
        self._fees = fees
        self._cancellation = cancellation

    async def execute(self, academy_id: str) -> BillingRulesView:
        schedule = await self._schedule.execute()
        fees = await self._fees.execute(academy_id)
        policy = await self._cancellation.execute()
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
                            key="manual_payer_reminders",
                            label="Reminders to manual payers",
                            editable=False,
                            display="Sent by hand from Payments. No automatic schedule.",
                        ),
                    ),
                ),
            )
        )


# --- Write -------------------------------------------------------------


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
    actor_id: str
    reason: str | None = None

    def requested(self) -> dict[str, int]:
        return {
            key: value for key in EDITABLE_RULE_KEYS if (value := getattr(self, key)) is not None
        }


class BillingRulesWriteResult(BaseModel):
    model_config = {"frozen": True}

    changed_fields: tuple[str, ...]


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
        audit: BillingAuditAppender | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._schedule_reader = schedule_reader
        self._schedule_writer = schedule_writer
        self._fees_reader = fees_reader
        self._fees_writer = fees_writer
        self._cancellation_reader = cancellation_reader
        self._cancellation_writer = cancellation_writer
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
        if not requested:
            return BillingRulesWriteResult(changed_fields=())

        schedule = await self._schedule_reader.execute()
        fees = await self._fees_reader.execute(academy_id)
        policy = await self._cancellation_reader.execute()
        before: dict[str, Any] = {
            "billing_day": schedule.billing_day,
            "invoice_due_days": schedule.invoice_due_days,
            "grace_days": fees.grace_days,
            "late_fee_cents": fees.late_fee_cents,
            "cancellation_minimum_notice_days": policy.cancellation_minimum_notice_days,
            "cancellation_fee_cents": policy.cancellation_fee_cents,
        }
        changed = {field: value for field, value in requested.items() if before[field] != value}
        if not changed:
            return BillingRulesWriteResult(changed_fields=())

        applied: list[str] = []
        try:
            await self._apply(academy_id, before, changed, applied)
        except Exception as exc:  # re-raised below, after the audit lands
            await self._append_audit(cmd, academy_id, before, tuple(applied), changed)
            raise BillingRulesPartialWriteError(tuple(applied), exc) from exc

        await self._append_audit(cmd, academy_id, before, tuple(applied), changed)
        return BillingRulesWriteResult(changed_fields=tuple(applied))

    async def _apply(
        self,
        academy_id: str,
        before: dict[str, Any],
        changed: dict[str, int],
        applied: list[str],
    ) -> None:
        schedule_fields = [f for f in ("billing_day", "invoice_due_days") if f in changed]
        if schedule_fields:
            await self._schedule_writer.execute(
                SetInvoiceScheduleCommand(
                    billing_day=changed.get("billing_day", before["billing_day"]),
                    invoice_due_days=changed.get("invoice_due_days", before["invoice_due_days"]),
                    actor_id="billing-rules",
                    reason="Settings -> Billing rules",
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
            for f in ("cancellation_minimum_notice_days", "cancellation_fee_cents")
            if f in changed
        ]
        if policy_fields:
            await self._cancellation_writer.execute(
                cancellation_minimum_notice_days=changed.get(
                    "cancellation_minimum_notice_days",
                    before["cancellation_minimum_notice_days"],
                ),
                cancellation_fee_cents=changed.get(
                    "cancellation_fee_cents", before["cancellation_fee_cents"]
                ),
            )
            applied.extend(policy_fields)

    async def _append_audit(
        self,
        cmd: UpdateBillingRulesCommand,
        academy_id: str,
        before: dict[str, Any],
        applied: tuple[str, ...],
        changed: dict[str, int],
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
