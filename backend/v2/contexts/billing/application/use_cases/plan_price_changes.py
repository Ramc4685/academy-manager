"""Change a plan price from a future month (Settings overhaul Phase 6 PR 26).

Pricing page card "Change a plan price · Preview first". The owner picks a
plan, a new price and an "apply from" month:

* :class:`PreviewPlanPriceChange` (read only): the classes linked to the plan
  (effective links only), the students each one bills, totals, and the
  same-price classes on a custom price that are NOT affected.
* :class:`SchedulePlanPriceChange`: re-validates everything the preview
  showed and records the change (plan, old and new price, month, the linked
  class ids, who, when). Audited. One scheduled change per plan.
* :class:`CancelPlanPriceChange`: owner, before the month starts and before
  anything for that month (or later) is charged or quoted. Audited.
* :class:`ApplyDuePlanPriceChanges`: the scheduler, once the month has
  started, moves the class fees and the plan price together so links stay
  current. Charges do not wait for it (see ``domain/plan_price_change.py``).

Recording a change writes only ``plan_price_changes`` and the audit log.
Nothing here writes an invoice, an invoice line or a payment.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel

from backend.v2.contexts.billing.application.ports import SessionTypeRepository
from backend.v2.contexts.billing.application.use_cases.money_setting_audit import (
    RecordMoneySettingChange,
)
from backend.v2.contexts.billing.application.use_cases.pricing_page import (
    ClassPlanLinkRepository,
    PricingReadModel,
    plan_prices,
)
from backend.v2.contexts.billing.domain.class_pricing import effective_plan_link
from backend.v2.contexts.billing.domain.errors import (
    PriceChangeAlreadyCharged,
    PriceChangeInFlight,
    PriceChangeInvalid,
    PriceChangeNotCancellable,
    PriceChangeNotFound,
    PriceChangePending,
    SessionTypeNotFound,
)
from backend.v2.contexts.billing.domain.plan_price_change import (
    PlanPriceChange,
    PriceChangeStatus,
    earliest_effective_period,
    ensure_effective_period_allowed,
    pending_change_for_class,
)
from backend.v2.shared.ids import new_ulid

log = logging.getLogger(__name__)

#: The actor a scheduler-applied change is audited as.
SYSTEM_ACTOR = "system:plan-price-change"


# --------------------------------------------------------------------- ports


class PlanPriceChangeRepository(Protocol):
    async def list_live(self) -> list[PlanPriceChange]: ...
    async def list_scheduled(self) -> list[PlanPriceChange]: ...
    async def get(self, change_id: str) -> PlanPriceChange | None: ...
    async def insert(self, change: PlanPriceChange) -> None:
        """Raise ``PriceChangePending`` when the plan already has a scheduled change."""
        ...

    async def begin_edit(
        self, change_id: str, session_ids: Sequence[str]
    ) -> tuple[str, PlanPriceChange] | None:
        """Hold a scheduled change for an owner edit: ``(token, fresh change)``.

        ``None`` when it is no longer scheduled or another edit holds it.
        """
        ...

    async def end_edit(self, change_id: str, token: str) -> None: ...
    async def cancel(self, change_id: str, *, token: str, actor_id: str, at: datetime) -> bool: ...
    async def record_flip(self, change_id: str, session_id: str, *, revision: int) -> bool:
        """False when the change moved on from ``revision``, is held by an edit,
        is no longer scheduled or no longer holds the class."""
        ...

    async def mark_applied(
        self, change_id: str, *, revision: int, plan_flipped: bool, at: datetime
    ) -> bool: ...


class InvoicedPeriodReader(Protocol):
    async def latest_invoiced_period(self, session_ids: Sequence[str]) -> str | None: ...
    async def has_charges_from(self, session_ids: Sequence[str], period: str) -> bool:
        """True when a month on or after ``period`` is charged or quoted for the classes."""
        ...


class PriceChangeFlipWriter(Protocol):
    async def current_class_fee(self, session_id: str) -> int | None: ...
    async def flip_class_fee(
        self, session_id: str, *, old_cents: int, new_cents: int, at: datetime
    ) -> bool: ...
    async def flip_plan_price(
        self, plan_id: str, *, old_cents: int, new_cents: int, at: datetime
    ) -> bool: ...


#: The academy's current billing month (``YYYY-MM``) on the monthly run's clock.
CurrentPeriod = Callable[[], Awaitable[str]]


# -------------------------------------------------------------------- views


class PriceChangeClassRow(BaseModel):
    model_config = {"frozen": True}

    session_id: str
    title: str
    #: Students the monthly run invoices on this class.
    students: int
    old_cents: int
    new_cents: int


class PriceChangeUnaffectedRow(BaseModel):
    model_config = {"frozen": True}

    session_id: str
    title: str
    charged_cents: int
    students: int


class PlanPriceChangePreview(BaseModel):
    model_config = {"frozen": True}

    plan_id: str
    plan_name: str
    old_cents: int
    new_cents: int
    effective_period: str
    #: The first month the owner may pick.
    earliest_period: str
    classes: list[PriceChangeClassRow]
    #: Custom-price classes at the plan's price: listed as not affected.
    not_affected: list[PriceChangeUnaffectedRow]
    total_classes: int
    total_students: int
    old_monthly_cents: int
    new_monthly_cents: int


class PlanPriceChangeView(BaseModel):
    model_config = {"frozen": True}

    change_id: str
    plan_id: str
    plan_name: str | None = None
    old_cents: int
    new_cents: int
    effective_period: str
    session_ids: list[str]
    status: PriceChangeStatus
    created_by: str
    created_at: datetime | None = None


class ScheduledClassFee(BaseModel):
    """A class whose fee moves at a future month ("Scheduled: $X from <Month>")."""

    model_config = {"frozen": True}

    session_id: str
    change_id: str
    plan_id: str
    new_cents: int
    effective_period: str


def change_view(change: PlanPriceChange, plan_name: str | None = None) -> PlanPriceChangeView:
    return PlanPriceChangeView(
        change_id=change.change_id,
        plan_id=change.plan_id,
        plan_name=plan_name,
        old_cents=change.old_cents,
        new_cents=change.new_cents,
        effective_period=change.effective_period,
        session_ids=list(change.session_ids),
        status=change.status,
        created_by=change.created_by,
        created_at=change.created_at,
    )


# ---------------------------------------------------------------- use cases


@dataclass(frozen=True)
class _PriceChangeDeps:
    session_types: SessionTypeRepository
    read_model: PricingReadModel
    links: ClassPlanLinkRepository
    changes: PlanPriceChangeRepository
    invoiced: InvoicedPeriodReader
    current_period: CurrentPeriod


class PreviewPlanPriceChange:
    """Read only: who a plan price change reaches, from which month."""

    def __init__(
        self,
        *,
        session_types: SessionTypeRepository,
        read_model: PricingReadModel,
        links: ClassPlanLinkRepository,
        changes: PlanPriceChangeRepository,
        invoiced: InvoicedPeriodReader,
        current_period: CurrentPeriod,
    ) -> None:
        self._d = _PriceChangeDeps(
            session_types, read_model, links, changes, invoiced, current_period
        )

    async def execute(
        self, *, plan_id: str, new_price_cents: int, effective_period: str | None = None
    ) -> PlanPriceChangePreview:
        d = self._d
        plan = await d.session_types.get(plan_id)
        if plan is None:
            raise SessionTypeNotFound("plan not found", session_type_id=plan_id)
        if not plan.is_active:
            raise PriceChangeInvalid("That plan is archived.", plan_id=plan_id)
        if new_price_cents < 0:
            raise PriceChangeInvalid("The price cannot be negative.", plan_id=plan_id)
        if new_price_cents == plan.price_cents:
            raise PriceChangeInvalid("That is the plan's current price.", plan_id=plan_id)
        if any(c.plan_id == plan_id for c in await d.changes.list_scheduled()):
            raise PriceChangePending(
                "This plan already has a scheduled price change. Cancel it first.",
                plan_id=plan_id,
            )

        prices = plan_prices(await d.session_types.list_all())
        stored = {link.session_id: link.plan_id for link in await d.links.list_links()}
        affected = []
        unaffected = []
        for cls in await d.read_model.list_classes():
            link = effective_plan_link(stored.get(cls.session_id), cls.charged_cents, prices)
            if link == plan_id:
                affected.append(cls)
            elif link is None and cls.charged_cents == plan.price_cents:
                unaffected.append(cls)

        affected_ids = [cls.session_id for cls in affected]
        earliest = earliest_effective_period(
            current_period=await d.current_period(),
            latest_invoiced_period=await d.invoiced.latest_invoiced_period(affected_ids),
        )
        month = effective_period or earliest
        ensure_effective_period_allowed(month, earliest=earliest)

        billed = await d.read_model.billed_students(affected_ids)
        rows = [
            PriceChangeClassRow(
                session_id=cls.session_id,
                title=cls.title,
                students=billed.get(cls.session_id, 0),
                old_cents=cls.charged_cents,
                new_cents=new_price_cents,
            )
            for cls in affected
        ]
        total_students = sum(row.students for row in rows)
        return PlanPriceChangePreview(
            plan_id=plan_id,
            plan_name=plan.name,
            old_cents=plan.price_cents,
            new_cents=new_price_cents,
            effective_period=month,
            earliest_period=earliest,
            classes=rows,
            not_affected=[
                PriceChangeUnaffectedRow(
                    session_id=cls.session_id,
                    title=cls.title,
                    charged_cents=cls.charged_cents,
                    students=cls.students,
                )
                for cls in unaffected
            ],
            total_classes=len(rows),
            total_students=total_students,
            old_monthly_cents=total_students * plan.price_cents,
            new_monthly_cents=total_students * new_price_cents,
        )


class SchedulePlanPriceChangeCommand(BaseModel):
    model_config = {"frozen": True}

    academy_id: str
    plan_id: str
    new_price_cents: int
    effective_period: str
    actor_id: str


class SchedulePlanPriceChange:
    """Owner applies a previewed change. Re-validates the month and the plan."""

    def __init__(
        self,
        *,
        preview: PreviewPlanPriceChange,
        changes: PlanPriceChangeRepository,
        audit: RecordMoneySettingChange,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._preview = preview
        self._changes = changes
        self._audit = audit
        self._now = clock

    async def execute(self, cmd: SchedulePlanPriceChangeCommand) -> PlanPriceChangeView:
        preview = await self._preview.execute(
            plan_id=cmd.plan_id,
            new_price_cents=cmd.new_price_cents,
            effective_period=cmd.effective_period,
        )
        change = PlanPriceChange(
            change_id=f"ppc-{new_ulid()}",
            plan_id=cmd.plan_id,
            old_cents=preview.old_cents,
            new_cents=preview.new_cents,
            effective_period=preview.effective_period,
            session_ids=tuple(row.session_id for row in preview.classes),
            created_by=cmd.actor_id,
            created_at=self._now(),
        )
        await self._changes.insert(change)
        await self._audit.execute(
            academy_id=cmd.academy_id,
            action="plan_price_change_scheduled",
            actor_id=cmd.actor_id,
            before={"plan_id": cmd.plan_id, "price_cents": preview.old_cents},
            after={
                "change_id": change.change_id,
                "plan_id": cmd.plan_id,
                "price_cents": preview.new_cents,
                "effective_period": change.effective_period,
                "session_ids": list(change.session_ids),
                "students": preview.total_students,
            },
        )
        return change_view(change, preview.plan_name)


class CancelPlanPriceChange:
    """Owner cancels a scheduled change before its month starts.

    Refused once anything for the effective month or later is charged or
    quoted for the change's classes (a registration quote, a checkout, a
    monthly run generated early): those were priced at the new price, and
    cancelling would leave the month with two prices.

    The check and the cancel run under an edit hold on the change (see
    ``domain/plan_price_change.py``): a registration quote cannot be stored
    while the hold is open, and one that straddled it is withdrawn, so no
    quote at the new price can land between the check and the cancel.
    """

    def __init__(
        self,
        *,
        changes: PlanPriceChangeRepository,
        current_period: CurrentPeriod,
        audit: RecordMoneySettingChange,
        charges: InvoicedPeriodReader,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._changes = changes
        self._current_period = current_period
        self._audit = audit
        self._charges = charges
        self._now = clock

    async def execute(self, *, academy_id: str, change_id: str, actor_id: str) -> None:
        change = await self._changes.get(change_id)
        if change is None:
            raise PriceChangeNotFound("price change not found", change_id=change_id)
        if (
            change.status != "scheduled"
            or change.flipped_session_ids
            or await self._current_period() >= change.effective_period
        ):
            raise PriceChangeNotCancellable(
                "This price change has taken effect or was cancelled.", change_id=change_id
            )
        held = await self._changes.begin_edit(change_id, change.session_ids)
        if held is None:
            latest = await self._changes.get(change_id)
            if latest is not None and latest.status == "scheduled":
                raise PriceChangeInFlight(
                    "This price change is being edited. Try again in a moment.",
                    change_id=change_id,
                )
            raise PriceChangeNotCancellable(
                "This price change has taken effect or was cancelled.", change_id=change_id
            )
        token, change = held
        try:
            if change.flipped_session_ids:
                raise PriceChangeNotCancellable(
                    "This price change has taken effect or was cancelled.", change_id=change_id
                )
            if await self._charges.has_charges_from(change.session_ids, change.effective_period):
                raise PriceChangeAlreadyCharged(
                    "Some charges from that month already use the new price, "
                    "so this change can no longer be cancelled.",
                    change_id=change_id,
                )
            if not await self._changes.cancel(
                change_id, token=token, actor_id=actor_id, at=self._now()
            ):
                raise PriceChangeNotCancellable(
                    "This price change has taken effect or was cancelled.", change_id=change_id
                )
        finally:
            await self._changes.end_edit(change_id, token)
        await self._audit.execute(
            academy_id=academy_id,
            action="plan_price_change_cancelled",
            actor_id=actor_id,
            before={
                "change_id": change_id,
                "plan_id": change.plan_id,
                "price_cents": change.new_cents,
                "effective_period": change.effective_period,
                "status": "scheduled",
            },
            after={"change_id": change_id, "plan_id": change.plan_id, "status": "cancelled"},
        )


class ListScheduledClassFees:
    """Classes whose fee a scheduled change will still move (admin-readable)."""

    def __init__(self, *, changes: PlanPriceChangeRepository, read_model: PricingReadModel) -> None:
        self._changes = changes
        self._read_model = read_model

    async def execute(self) -> list[ScheduledClassFee]:
        scheduled = await self._changes.list_scheduled()
        if not scheduled:
            return []
        out: list[ScheduledClassFee] = []
        seen: set[str] = set()
        for change in scheduled:
            for session_id in change.session_ids:
                if session_id in seen:
                    continue
                cls = await self._read_model.get_class(session_id)
                if cls is None:
                    continue
                pending = pending_change_for_class(
                    session_id=session_id,
                    stored_fee_cents=cls.charged_cents,
                    changes=scheduled,
                )
                if pending is None:
                    continue
                seen.add(session_id)
                out.append(
                    ScheduledClassFee(
                        session_id=session_id,
                        change_id=pending.change_id,
                        plan_id=pending.plan_id,
                        new_cents=pending.new_cents,
                        effective_period=pending.effective_period,
                    )
                )
        return out


class ApplyDuePlanPriceChangesResult(BaseModel):
    model_config = {"frozen": True}

    applied: int
    classes_moved: int


class ApplyDuePlanPriceChanges:
    """Scheduler: once a change's month has started, move fees and plan price together.

    Idempotent and safe to re-run: every write is compare-and-set against the
    old price, and a class is recorded as flipped before its fee moves. Does
    not change any charge (the charge paths already read the new price for
    the month); it keeps links current and the class editor accurate.

    The change's flips and its "applied" mark are compare-and-set on the
    revision read at the start, so a change the owner edits mid-run (a class
    joining or leaving) is left scheduled and picked up whole by the next run
    rather than applied from a stale list of classes.
    """

    def __init__(
        self,
        *,
        changes: PlanPriceChangeRepository,
        flips: PriceChangeFlipWriter,
        audit: RecordMoneySettingChange,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._changes = changes
        self._flips = flips
        self._audit = audit
        self._now = clock

    async def execute(self, *, academy_id: str, period: str) -> ApplyDuePlanPriceChangesResult:
        applied = moved = 0
        for change in await self._changes.list_scheduled():
            if change.effective_period > period:
                continue
            now = self._now()
            flipped: list[str] = []
            deferred = False
            for session_id in change.session_ids:
                if session_id in change.flipped_session_ids:
                    flipped.append(session_id)
                    continue
                if await self._flips.current_class_fee(session_id) != change.old_cents:
                    continue  # fee edited by hand since: the owner's fee wins
                if not await self._changes.record_flip(
                    change.change_id, session_id, revision=change.revision
                ):
                    # Cancelled, or the owner is editing (or edited) the
                    # change since it was read: leave it for the next run.
                    deferred = True
                    break
                flipped.append(session_id)
                if await self._flips.flip_class_fee(
                    session_id, old_cents=change.old_cents, new_cents=change.new_cents, at=now
                ):
                    moved += 1
            if deferred:
                continue
            plan_flipped = await self._flips.flip_plan_price(
                change.plan_id, old_cents=change.old_cents, new_cents=change.new_cents, at=now
            )
            if not await self._changes.mark_applied(
                change.change_id, revision=change.revision, plan_flipped=plan_flipped, at=now
            ):
                continue
            applied += 1
            log.info(
                "plan_price_change_applied",
                extra={
                    "academy_id": academy_id,
                    "change_id": change.change_id,
                    "classes_moved": len(flipped),
                    "plan_flipped": plan_flipped,
                },
            )
            await self._audit.execute(
                academy_id=academy_id,
                action="plan_price_change_applied",
                actor_id=SYSTEM_ACTOR,
                before={
                    "change_id": change.change_id,
                    "plan_id": change.plan_id,
                    "price_cents": change.old_cents,
                },
                after={
                    "change_id": change.change_id,
                    "plan_id": change.plan_id,
                    "price_cents": change.new_cents,
                    "effective_period": change.effective_period,
                    "session_ids": flipped,
                    "plan_price_moved": plan_flipped,
                },
            )
        return ApplyDuePlanPriceChangesResult(applied=applied, classes_moved=moved)
