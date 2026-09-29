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
from typing import Literal, Protocol

from pydantic import BaseModel

from backend.v2.contexts.billing.application.ports import SessionTypeRepository
from backend.v2.contexts.billing.application.use_cases.money_setting_audit import (
    RecordMoneySettingChange,
)
from backend.v2.contexts.billing.domain.class_pricing import (
    PlanPrice,
    effective_plan_link,
    ensure_link_allowed,
    initial_plan_link,
    matching_plan_ids,
)
from backend.v2.contexts.billing.domain.errors import PricingClassNotFound, SessionTypeNotFound
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


def _plan_prices(plans: Sequence[SessionType]) -> list[PlanPrice]:
    return [
        PlanPrice(plan_id=p.session_type_id, price_cents=p.price_cents, is_active=p.is_active)
        for p in plans
    ]


# ---------------------------------------------------------------- use cases


class GetPricingOverview:
    def __init__(
        self,
        *,
        session_types: SessionTypeRepository,
        read_model: PricingReadModel,
        links: ClassPlanLinkRepository,
    ) -> None:
        self._session_types = session_types
        self._read_model = read_model
        self._links = links

    async def execute(self) -> PricingOverview:
        plans = await self._session_types.list_all()
        prices = _plan_prices(plans)
        classes = await self._read_model.list_classes()
        stored = {link.session_id: link for link in await self._links.list_links()}

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
                )
            )

        overrides = await self._read_model.list_saved_overrides(plans)
        return PricingOverview(
            plans=[
                PricingPlanRow(plan=p, linked_classes=linked_counts.get(p.session_type_id, 0))
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
    ) -> None:
        self._session_types = session_types
        self._read_model = read_model
        self._links = links
        self._audit = audit
        self._now = clock

    async def execute(self, cmd: SetClassPlanLinkCommand) -> PricingClassRow:
        cls = await self._read_model.get_class(cmd.session_id)
        if cls is None:
            raise PricingClassNotFound("class not found", session_id=cmd.session_id)
        plans = await self._session_types.list_all()
        prices = _plan_prices(plans)
        if cmd.plan_id is not None:
            plan = next((p for p in prices if p.plan_id == cmd.plan_id), None)
            if plan is None:
                raise SessionTypeNotFound("plan not found", session_type_id=cmd.plan_id)
            ensure_link_allowed(cls.charged_cents, plan)

        previous = await self._links.get_link(cmd.session_id)
        await self._links.set_link(
            session_id=cmd.session_id,
            plan_id=cmd.plan_id,
            actor_id=cmd.actor_id,
            at=self._now(),
        )
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
    ) -> None:
        self._session_types = session_types
        self._read_model = read_model
        self._links = links
        self._audit = audit
        self._now = clock

    async def execute(self, *, academy_id: str, actor_id: str) -> LinkMatchingClassesResult:
        prices = _plan_prices(await self._session_types.list_all())
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
            if await self._links.set_link_if_unset(
                session_id=cls.session_id, plan_id=plan_id, actor_id=actor_id, at=now
            ):
                linked.append({"session_id": cls.session_id, "plan_id": plan_id})
            else:
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
