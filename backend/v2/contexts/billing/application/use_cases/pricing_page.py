"""Pricing page use cases (Settings overhaul Phase 3 PR 11b).

The Pricing page (``/admin/pricing``, owner-only) shows three things:

* **Plans**: the session types (the academy price list), each with its plan
  type and how many classes are linked to it.
* **Where each class's price comes from**: every class, the plan it is linked
  to (or "Custom"), and what it is actually charged per month, which is the
  class's own monthly fee read with the SAME helper the monthly invoice
  generator uses.
* **Saved price overrides**: per-student override amounts stored by the two
  owner "override price" buttons that no charge path reads. Listed for review
  only; nothing here turns them into a price.

Zero change to any charged amount is the hard rule. A link is a label, never
an amount: these use cases never write a fee, and no charge path reads a link
(the links live in their own ``class_plan_links`` collection). See
``domain/class_pricing.py`` for the link rules.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from backend.v2.contexts.billing.application.ports import SessionTypeRepository
from backend.v2.contexts.billing.application.use_cases.money_setting_audit import (
    RecordMoneySettingChange,
)
from backend.v2.contexts.billing.domain.class_pricing import (
    PlanPrice,
    StaleLinkReason,
    effective_plan_link,
    ensure_link_allowed,
    initial_plan_link,
    matching_plan_ids,
    stale_link_reason,
)
from backend.v2.contexts.billing.domain.errors import (
    PriceChangeAlreadyCharged,
    PriceChangeInFlight,
    PricingClassNotFound,
    SessionTypeNotFound,
)
from backend.v2.contexts.billing.domain.plan_price_change import (
    PlanPriceChange,
    pending_change_for_class,
)
from backend.v2.contexts.billing.domain.session_type import SessionType

log = logging.getLogger(__name__)


# --------------------------------------------------------------------- ports


@dataclass(frozen=True)
class ClassPriceFacts:
    """One class as billing sees it."""

    session_id: str
    title: str
    #: What the class is charged per month: the monthly invoice generator's
    #: own reading of the class fee (``session_amount_cents``).
    charged_cents: int
    #: False when the class has no fee stored at all (it is billed at 0).
    fee_set: bool
    #: Active enrollments on the class.
    students: int


SavedOverrideSource = Literal["billing_plan", "class_enrollment"]


@dataclass(frozen=True)
class SavedOverrideFacts:
    """A per-student price saved by an owner "override price" button.

    ``billing_plan``: ``student_billing_enrollments.override_price_cents``
    (Student > Billing plans > Override price). ``class_enrollment``: the
    amount saved on a class enrollment (Student > Sessions > Override fee).
    Neither is read by the monthly invoice, checkout or "Bill this month".
    """

    source: SavedOverrideSource
    enrollment_id: str
    student_id: str | None
    student_name: str | None
    #: The class title or plan name the override was saved against.
    label: str | None
    override_cents: int
    #: What the student's class or plan is charged today, when known.
    charged_cents: int | None
    status: str | None


class PricingReadModel(Protocol):
    async def list_classes(self) -> list[ClassPriceFacts]: ...
    async def get_class(self, session_id: str) -> ClassPriceFacts | None: ...
    async def list_saved_overrides(
        self, plans: Sequence[SessionType]
    ) -> list[SavedOverrideFacts]: ...
    async def billed_students(self, session_ids: Sequence[str]) -> dict[str, int]:
        """Students the monthly run invoices on each class (its own status rule)."""
        ...


@dataclass(frozen=True)
class ClassPlanLink:
    """A stored decision for one class: a plan id, or ``None`` for custom."""

    session_id: str
    plan_id: str | None


class ClassPlanLinkRepository(Protocol):
    async def list_links(self) -> list[ClassPlanLink]: ...
    async def get_link(self, session_id: str) -> ClassPlanLink | None: ...
    async def set_link(
        self, *, session_id: str, plan_id: str | None, actor_id: str, at: datetime
    ) -> None: ...
    async def set_link_if_unset(
        self, *, session_id: str, plan_id: str, actor_id: str, at: datetime
    ) -> bool:
        """Insert a link only when the class has no decision yet; True if written."""
        ...


# -------------------------------------------------------------------- views


class PricingPlanRow(BaseModel):
    model_config = {"frozen": True}

    plan: SessionType
    linked_classes: int
    #: The plan's scheduled price change, if any (PR 26).
    scheduled_change_id: str | None = None
    scheduled_cents: int | None = None
    scheduled_from: str | None = None


class PricingClassRow(BaseModel):
    model_config = {"frozen": True}

    session_id: str
    title: str
    charged_cents: int
    fee_set: bool
    students: int
    #: The plan the class is priced from, or ``None`` for custom.
    plan_id: str | None
    #: Active plans at exactly this class's fee: the only plans it may use.
    matching_plan_ids: list[str]
    #: A stored link whose plan price no longer equals the fee (shown custom).
    stale_link: bool
    #: Why the stored link is stale: "archived", "price_changed" or "plan_removed".
    stale_reason: StaleLinkReason | None = None
    #: A scheduled plan price change that will move this class's fee (PR 26).
    scheduled_cents: int | None = None
    scheduled_from: str | None = None


class PricingSavedOverride(BaseModel):
    model_config = {"frozen": True}

    source: SavedOverrideSource
    enrollment_id: str
    student_id: str | None
    student_name: str | None
    label: str | None
    override_cents: int
    charged_cents: int | None
    status: str | None


class PricingOverview(BaseModel):
    model_config = {"frozen": True}

    plans: list[PricingPlanRow]
    classes: list[PricingClassRow]
    saved_overrides: list[PricingSavedOverride]
    #: Undecided classes "Link matching classes" would link right now.
    auto_linkable: int


class PriceChangeLister(Protocol):
    """The part of the plan price change store the overview reads (PR 26)."""

    async def list_scheduled(self) -> list[PlanPriceChange]: ...


class PriceChangeMembership(Protocol):
    """Which classes a scheduled plan price change reaches (PR 26)."""

    async def list_scheduled(self) -> list[PlanPriceChange]: ...
    async def get(self, change_id: str) -> PlanPriceChange | None: ...
    async def begin_edit(
        self, change_id: str, session_ids: Sequence[str]
    ) -> tuple[str, PlanPriceChange] | None: ...
    async def end_edit(self, change_id: str, token: str) -> None: ...
    async def add_session(self, change_id: str, session_id: str, *, token: str) -> bool: ...
    async def remove_session(self, change_id: str, session_id: str, *, token: str) -> bool: ...


class ChargedMonthReader(Protocol):
    async def has_charges_from(self, session_ids: Sequence[str], period: str) -> bool:
        """True when a month on or after ``period`` is charged or quoted for the classes."""
        ...


@dataclass(frozen=True)
class _Hold:
    change_id: str
    token: str


@dataclass(frozen=True)
class _MembershipMoves:
    """Moves to make once the link is written, each under an edit hold on its change."""

    remove: tuple[_Hold, ...] = ()
    add: tuple[_Hold, ...] = ()
    #: Holds taken for a change that turned out to need no move.
    idle: tuple[_Hold, ...] = ()

    def holds(self) -> tuple[_Hold, ...]:
        return self.remove + self.add + self.idle


@dataclass(frozen=True)
class _AppliedMoves:
    left: tuple[str, ...] = ()
    joined: tuple[str, ...] = ()

    def audit_fields(self) -> dict[str, object]:
        """Only present when a link moved a class in or out of a scheduled change."""
        out: dict[str, object] = {}
        if self.left:
            out["price_changes_left"] = list(self.left)
        if self.joined:
            out["price_changes_joined"] = list(self.joined)
        return out


async def _release(membership: PriceChangeMembership | None, holds: Sequence[_Hold]) -> None:
    if membership is None:
        return
    for hold in holds:
        await membership.end_edit(hold.change_id, hold.token)


async def _plan_membership_moves(
    *,
    membership: PriceChangeMembership | None,
    charges: ChargedMonthReader | None,
    session_id: str,
    plan_id: str | None,
    fee_cents: int,
) -> _MembershipMoves:
    """Keep scheduled plan price changes in step with a class's link.

    A class moved off a plan (to custom or another plan) leaves that plan's
    scheduled change, so it keeps its own fee. A class linked to a plan with
    a scheduled change at the change's old price joins it, so its link does
    not go stale when the plan price moves. Either move is refused (or, for
    a join, skipped) when a month on or after the change is already charged
    or quoted for the class: those charges must keep matching the month.

    Each change a move may touch is held for an owner edit first (see
    ``domain/plan_price_change.py``), and the move is decided from the change
    as it stands under the hold: no quote for the class can be stored and the
    scheduler cannot flip the class until the caller applies the moves with
    :func:`_apply_membership_moves` (which releases every hold). On an error
    here every hold taken is released.
    """
    if membership is None:
        return _MembershipMoves()
    remove: list[_Hold] = []
    add: list[_Hold] = []
    idle: list[_Hold] = []
    try:
        for listed in await membership.list_scheduled():
            leaving = session_id in listed.session_ids and listed.plan_id != plan_id
            joining = (
                session_id not in listed.session_ids
                and listed.plan_id == plan_id
                and fee_cents == listed.old_cents
            )
            if not (leaving or joining):
                continue
            held = await membership.begin_edit(listed.change_id, [session_id])
            if held is None:
                latest = await membership.get(listed.change_id)
                if latest is not None and latest.status == "scheduled":
                    raise PriceChangeInFlight(
                        "A plan price change for this class is being edited. "
                        "Try again in a moment.",
                        session_id=session_id,
                        change_id=listed.change_id,
                    )
                continue  # applied or cancelled since it was listed
            token, change = held
            hold = _Hold(change.change_id, token)
            in_change = session_id in change.session_ids
            applies = fee_cents == change.old_cents
            if in_change and change.plan_id != plan_id:
                if session_id in change.flipped_session_ids:
                    idle.append(hold)
                    continue
                if (
                    applies
                    and charges is not None
                    and await charges.has_charges_from([session_id], change.effective_period)
                ):
                    idle.append(hold)
                    raise PriceChangeAlreadyCharged(
                        "This class already has charges at the plan's new price. "
                        "It stays on the plan.",
                        session_id=session_id,
                        change_id=change.change_id,
                    )
                remove.append(hold)
            elif not in_change and change.plan_id == plan_id and applies:
                if charges is None or await charges.has_charges_from(
                    [session_id], change.effective_period
                ):
                    idle.append(hold)  # already charged at today's price for that month
                    continue
                add.append(hold)
            else:
                idle.append(hold)
    except BaseException:
        await _release(membership, remove + add + idle)
        raise
    return _MembershipMoves(remove=tuple(remove), add=tuple(add), idle=tuple(idle))


async def _apply_membership_moves(
    membership: PriceChangeMembership | None, session_id: str, moves: _MembershipMoves
) -> _AppliedMoves:
    """Write the planned moves; returns the ones that were written. Releases every hold."""
    if membership is None:
        return _AppliedMoves()
    left: list[str] = []
    joined: list[str] = []
    try:
        for hold in moves.remove:
            if await membership.remove_session(hold.change_id, session_id, token=hold.token):
                left.append(hold.change_id)
            else:
                log.warning(
                    "plan_price_change_move_skipped",
                    extra={"change_id": hold.change_id, "session_id": session_id, "move": "leave"},
                )
        for hold in moves.add:
            if await membership.add_session(hold.change_id, session_id, token=hold.token):
                joined.append(hold.change_id)
            else:
                log.warning(
                    "plan_price_change_move_skipped",
                    extra={"change_id": hold.change_id, "session_id": session_id, "move": "join"},
                )
    finally:
        await _release(membership, moves.holds())
    return _AppliedMoves(left=tuple(left), joined=tuple(joined))


def plan_prices(plans: Sequence[SessionType]) -> list[PlanPrice]:
    return [
        PlanPrice(plan_id=p.session_type_id, price_cents=p.price_cents, is_active=p.is_active)
        for p in plans
    ]


def _change_attr(changes: dict[str, PlanPriceChange], plan: SessionType, attr: str) -> Any:
    change = changes.get(plan.session_type_id)
    return getattr(change, attr) if change is not None else None


# ---------------------------------------------------------------- use cases


class GetPricingOverview:
    def __init__(
        self,
        *,
        session_types: SessionTypeRepository,
        read_model: PricingReadModel,
        links: ClassPlanLinkRepository,
        price_changes: PriceChangeLister | None = None,
    ) -> None:
        self._session_types = session_types
        self._read_model = read_model
        self._links = links
        self._price_changes = price_changes

    async def execute(self) -> PricingOverview:
        plans = await self._session_types.list_all()
        prices = plan_prices(plans)
        classes = await self._read_model.list_classes()
        stored = {link.session_id: link for link in await self._links.list_links()}
        scheduled = (
            await self._price_changes.list_scheduled() if self._price_changes is not None else []
        )
        change_by_plan = {change.plan_id: change for change in scheduled}

        linked_counts: dict[str, int] = {}
        rows: list[PricingClassRow] = []
        auto_linkable = 0
        for cls in classes:
            decision = stored.get(cls.session_id)
            stored_plan = decision.plan_id if decision else None
            plan_id = effective_plan_link(stored_plan, cls.charged_cents, prices)
            if plan_id is not None:
                linked_counts[plan_id] = linked_counts.get(plan_id, 0) + 1
            if decision is None and initial_plan_link(cls.charged_cents, prices) is not None:
                auto_linkable += 1
            pending = pending_change_for_class(
                session_id=cls.session_id, stored_fee_cents=cls.charged_cents, changes=scheduled
            )
            rows.append(
                PricingClassRow(
                    session_id=cls.session_id,
                    title=cls.title,
                    charged_cents=cls.charged_cents,
                    fee_set=cls.fee_set,
                    students=cls.students,
                    plan_id=plan_id,
                    matching_plan_ids=matching_plan_ids(cls.charged_cents, prices),
                    stale_link=stored_plan is not None and plan_id is None,
                    stale_reason=stale_link_reason(stored_plan, cls.charged_cents, prices),
                    scheduled_cents=pending.new_cents if pending else None,
                    scheduled_from=pending.effective_period if pending else None,
                )
            )

        overrides = await self._read_model.list_saved_overrides(plans)
        return PricingOverview(
            plans=[
                PricingPlanRow(
                    plan=p,
                    linked_classes=linked_counts.get(p.session_type_id, 0),
                    scheduled_change_id=_change_attr(change_by_plan, p, "change_id"),
                    scheduled_cents=_change_attr(change_by_plan, p, "new_cents"),
                    scheduled_from=_change_attr(change_by_plan, p, "effective_period"),
                )
                for p in plans
            ],
            classes=rows,
            saved_overrides=[
                PricingSavedOverride(
                    source=o.source,
                    enrollment_id=o.enrollment_id,
                    student_id=o.student_id,
                    student_name=o.student_name,
                    label=o.label,
                    override_cents=o.override_cents,
                    charged_cents=o.charged_cents,
                    status=o.status,
                )
                for o in overrides
            ],
            auto_linkable=auto_linkable,
        )


class SetClassPlanLinkCommand(BaseModel):
    model_config = {"frozen": True}

    academy_id: str
    session_id: str
    #: A plan id, or ``None`` to mark the class custom.
    plan_id: str | None
    actor_id: str


class SetClassPlanLink:
    """Owner links one class to a plan at its own fee, or marks it custom.

    Never writes an amount. Refused (409) when the plan's price is not the
    class fee or the plan is archived, so a link cannot misstate a charge.
    """

    def __init__(
        self,
        *,
        session_types: SessionTypeRepository,
        read_model: PricingReadModel,
        links: ClassPlanLinkRepository,
        audit: RecordMoneySettingChange,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        price_changes: PriceChangeMembership | None = None,
        charges: ChargedMonthReader | None = None,
    ) -> None:
        self._session_types = session_types
        self._read_model = read_model
        self._links = links
        self._audit = audit
        self._now = clock
        self._price_changes = price_changes
        self._charges = charges

    async def execute(self, cmd: SetClassPlanLinkCommand) -> PricingClassRow:
        cls = await self._read_model.get_class(cmd.session_id)
        if cls is None:
            raise PricingClassNotFound("class not found", session_id=cmd.session_id)
        plans = await self._session_types.list_all()
        prices = plan_prices(plans)
        if cmd.plan_id is not None:
            plan = next((p for p in prices if p.plan_id == cmd.plan_id), None)
            if plan is None:
                raise SessionTypeNotFound("plan not found", session_type_id=cmd.plan_id)
            ensure_link_allowed(cls.charged_cents, plan)

        moves = await _plan_membership_moves(
            membership=self._price_changes,
            charges=self._charges,
            session_id=cmd.session_id,
            plan_id=cmd.plan_id,
            fee_cents=cls.charged_cents,
        )
        try:
            previous = await self._links.get_link(cmd.session_id)
            await self._links.set_link(
                session_id=cmd.session_id,
                plan_id=cmd.plan_id,
                actor_id=cmd.actor_id,
                at=self._now(),
            )
        except BaseException:
            await _release(self._price_changes, moves.holds())
            raise
        applied = await _apply_membership_moves(self._price_changes, cmd.session_id, moves)
        await self._audit.execute(
            academy_id=cmd.academy_id,
            action="class_plan_link_changed",
            actor_id=cmd.actor_id,
            before={
                "session_id": cmd.session_id,
                "plan_id": previous.plan_id if previous else None,
                "decided": previous is not None,
            },
            after={
                "session_id": cmd.session_id,
                "plan_id": cmd.plan_id,
                "decided": True,
                # The fee is unchanged by a link; recorded so the trail shows
                # what the class was charged when it was linked.
                "charged_cents": cls.charged_cents,
                **applied.audit_fields(),
            },
        )
        return PricingClassRow(
            session_id=cls.session_id,
            title=cls.title,
            charged_cents=cls.charged_cents,
            fee_set=cls.fee_set,
            students=cls.students,
            plan_id=cmd.plan_id,
            matching_plan_ids=matching_plan_ids(cls.charged_cents, prices),
            stale_link=False,
        )


class LinkMatchingClassesResult(BaseModel):
    model_config = {"frozen": True}

    #: Classes linked by this run (exactly one plan at their fee).
    linked: int
    #: Undecided classes left custom: no plan has their fee.
    no_match: int
    #: Undecided classes left custom: two or more plans have their fee.
    several_matches: int
    #: Classes the owner (or an earlier run) already decided; untouched.
    already_decided: int


class LinkMatchingClasses:
    """Owner-triggered, idempotent initial link.

    Links each class that has no decision yet to the ONE active plan whose
    price equals its fee. Zero or several matches leave it custom (and
    undecided, so a later run can link it once the price list is tidied).
    A class the owner already decided is never touched. Writes no amount.
    """

    def __init__(
        self,
        *,
        session_types: SessionTypeRepository,
        read_model: PricingReadModel,
        links: ClassPlanLinkRepository,
        audit: RecordMoneySettingChange,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        price_changes: PriceChangeMembership | None = None,
        charges: ChargedMonthReader | None = None,
    ) -> None:
        self._session_types = session_types
        self._read_model = read_model
        self._links = links
        self._audit = audit
        self._now = clock
        self._price_changes = price_changes
        self._charges = charges

    async def execute(self, *, academy_id: str, actor_id: str) -> LinkMatchingClassesResult:
        prices = plan_prices(await self._session_types.list_all())
        decided = {link.session_id for link in await self._links.list_links()}
        linked: list[dict[str, object]] = []
        no_match = several = already = 0
        now = self._now()
        for cls in await self._read_model.list_classes():
            if cls.session_id in decided:
                already += 1
                continue
            plan_id = initial_plan_link(cls.charged_cents, prices)
            if plan_id is None:
                if matching_plan_ids(cls.charged_cents, prices):
                    several += 1
                else:
                    no_match += 1
                continue
            moves = await _plan_membership_moves(
                membership=self._price_changes,
                charges=self._charges,
                session_id=cls.session_id,
                plan_id=plan_id,
                fee_cents=cls.charged_cents,
            )
            try:
                was_unset = await self._links.set_link_if_unset(
                    session_id=cls.session_id, plan_id=plan_id, actor_id=actor_id, at=now
                )
            except BaseException:
                await _release(self._price_changes, moves.holds())
                raise
            if was_unset:
                applied = await _apply_membership_moves(self._price_changes, cls.session_id, moves)
                linked.append(
                    {"session_id": cls.session_id, "plan_id": plan_id, **applied.audit_fields()}
                )
            else:
                await _release(self._price_changes, moves.holds())
                already += 1

        result = LinkMatchingClassesResult(
            linked=len(linked),
            no_match=no_match,
            several_matches=several,
            already_decided=already,
        )
        log.info(
            "pricing_link_matching_classes",
            extra={"academy_id": academy_id, "actor_id": actor_id, **result.model_dump()},
        )
        if linked:
            await self._audit.execute(
                academy_id=academy_id,
                action="class_plan_links_matched",
                actor_id=actor_id,
                before={"linked": []},
                after={"linked": linked, **result.model_dump()},
            )
        return result
