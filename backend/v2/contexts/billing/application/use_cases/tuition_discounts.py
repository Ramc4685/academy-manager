"""Set / remove recurring tuition discount policies (billing application layer)."""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol

from pydantic import BaseModel, Field

from backend.v2.contexts.billing.domain.tuition_discount import (
    DiscountCategory,
    DiscountKind,
    TuitionDiscount,
    display_label,
    monthly_discount_cents,
)
from backend.v2.shared.tenancy import TenantScopedRepository


class TuitionDiscountPort(Protocol):
    async def set_active(self, policy: TuitionDiscount, *, set_by: str) -> TuitionDiscount: ...

    async def remove(self, enrollment_id: str, *, ended_by: str) -> None: ...


class TuitionDiscountReadPort(Protocol):
    async def active_by_enrollments(
        self, enrollment_ids: list[str]
    ) -> dict[str, TuitionDiscount]: ...


async def attach_tuition_discount_badges(
    sessions: list[dict],
    discounts: TuitionDiscountReadPort | None,
) -> None:
    """Enrich enrolled-session summaries with recurring tuition discount badges (#244).

    Lives in the application layer so the admin BFF can compose discount badges
    without importing the billing domain directly (DDD boundary). Mutates the
    ``sessions`` dicts in place, adding a ``discount`` key where a policy applies.
    """
    if discounts is None or not sessions:
        return
    enrollment_ids = [str(s.get("enrollment_id")) for s in sessions if s.get("enrollment_id")]
    if not enrollment_ids:
        return
    policies = await discounts.active_by_enrollments(enrollment_ids)
    for summary in sessions:
        policy = policies.get(str(summary.get("enrollment_id")))
        if policy is None:
            continue
        gross = int(summary.get("amount_cents") or 0)
        discount_cents = monthly_discount_cents(policy, monthly_price_cents=gross)
        summary["discount"] = {
            "category": policy.category,
            "category_label": policy.category_label,
            "kind": policy.kind,
            "label": display_label(policy),
            "gross_cents": gross,
            "discount_cents": discount_cents,
            "net_cents": max(gross - discount_cents, 0),
            "status": policy.status,
            "effective_start": policy.effective_start,
            "effective_end": policy.effective_end,
        }


class SetTuitionDiscountCommand(BaseModel):
    model_config = {"frozen": True}

    discount_id: str
    enrollment_id: str
    student_id: str
    category: DiscountCategory
    category_label: str | None = None
    kind: DiscountKind
    percent_bps: int | None = None
    amount_off_cents: int | None = None
    fixed_net_cents: int | None = None
    effective_start: date
    effective_end: date | None = None
    note: str | None = None
    set_by: str


class SetTuitionDiscount:
    def __init__(self, *, discounts: TuitionDiscountPort) -> None:
        self._discounts = discounts

    async def execute(self, cmd: SetTuitionDiscountCommand) -> TuitionDiscount:
        policy = TuitionDiscount(
            discount_id=cmd.discount_id,
            enrollment_id=cmd.enrollment_id,
            student_id=cmd.student_id,
            category=cmd.category,
            category_label=cmd.category_label,
            kind=cmd.kind,
            percent_bps=cmd.percent_bps,
            amount_off_cents=cmd.amount_off_cents,
            fixed_net_cents=cmd.fixed_net_cents,
            effective_start=cmd.effective_start,
            effective_end=cmd.effective_end,
            note=cmd.note,
        )
        return await self._discounts.set_active(policy, set_by=cmd.set_by)


class RemoveTuitionDiscountCommand(BaseModel):
    model_config = {"frozen": True}

    enrollment_id: str
    ended_by: str


class RemoveTuitionDiscount:
    def __init__(self, *, discounts: TuitionDiscountPort) -> None:
        self._discounts = discounts

    async def execute(self, cmd: RemoveTuitionDiscountCommand) -> None:
        await self._discounts.remove(cmd.enrollment_id, ended_by=cmd.ended_by)


class TuitionDiscountBackfillCandidate(BaseModel):
    model_config = {"frozen": True}

    enrollment_id: str
    student_id: str | None = None
    session_id: str
    session_title: str
    billed_cents: int = Field(ge=0)
    session_price_cents: int = Field(ge=0)
    delta_cents: int = Field(ge=0)
    payment_mode: str | None = None


class TuitionDiscountBackfillCandidateList(BaseModel):
    model_config = {"frozen": True}

    candidates: list[TuitionDiscountBackfillCandidate]


class MongoTuitionDiscountBackfillCandidateQuery(TenantScopedRepository):
    """Read-only listing for legacy below-price rows without active discount policies."""

    collection_name = "enrollments"

    async def execute(self, *, limit: int | None = None) -> TuitionDiscountBackfillCandidateList:
        enrollments = [
            doc
            async for doc in self._find_many(
                {"status": "active", "is_deleted": {"$ne": True}},
                sort=[("student_id", 1), ("enrollment_id", 1)],
                limit=limit,
            )
        ]
        if not enrollments:
            return TuitionDiscountBackfillCandidateList(candidates=[])

        session_ids = sorted(
            {str(doc.get("session_id")) for doc in enrollments if doc.get("session_id") is not None}
        )
        enrollment_ids = sorted(
            {
                str(doc.get("enrollment_id") or doc.get("_id"))
                for doc in enrollments
                if doc.get("enrollment_id") is not None or doc.get("_id") is not None
            }
        )
        sessions_by_id = await self._sessions_by_id(session_ids)
        active_discount_enrollment_ids = await self._active_discount_enrollment_ids(enrollment_ids)

        candidates: list[TuitionDiscountBackfillCandidate] = []
        for enrollment in enrollments:
            enrollment_id = str(enrollment.get("enrollment_id") or enrollment.get("_id") or "")
            session_id = str(enrollment.get("session_id") or "")
            if (
                not enrollment_id
                or not session_id
                or enrollment_id in active_discount_enrollment_ids
            ):
                continue
            session = sessions_by_id.get(session_id)
            if session is None:
                continue
            billed_cents = _cents_value(
                enrollment,
                ("final_amount_cents", "amount_cents", "gross_amount_cents"),
                ("final_amount", "amount"),
            )
            session_price_cents = _cents_value(
                session,
                ("monthly_price_cents", "price_cents", "amount_cents", "gross_amount_cents"),
                ("monthly_price", "price", "amount"),
            )
            if billed_cents is None or session_price_cents is None:
                continue
            if billed_cents >= session_price_cents:
                continue
            candidates.append(
                TuitionDiscountBackfillCandidate(
                    enrollment_id=enrollment_id,
                    student_id=_optional_str(enrollment.get("student_id")),
                    session_id=session_id,
                    session_title=str(
                        session.get("title") or session.get("name") or "Academy session"
                    ),
                    billed_cents=max(billed_cents, 0),
                    session_price_cents=max(session_price_cents, 0),
                    delta_cents=max(session_price_cents - billed_cents, 0),
                    payment_mode=_optional_str(enrollment.get("payment_mode")),
                )
            )
        return TuitionDiscountBackfillCandidateList(candidates=candidates)

    async def _sessions_by_id(self, session_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not session_ids:
            return {}
        out: dict[str, dict[str, Any]] = {}
        async for session in self._find_many_in_collection(
            "sessions",
            {"session_id": {"$in": session_ids}},
        ):
            session_id = str(session.get("session_id") or "")
            if session_id:
                out[session_id] = session
        return out

    async def _active_discount_enrollment_ids(self, enrollment_ids: list[str]) -> set[str]:
        if not enrollment_ids:
            return set()
        out: set[str] = set()
        async for policy in self._find_many_in_collection(
            "enrollment_discounts",
            {"enrollment_id": {"$in": enrollment_ids}, "status": "active"},
            {"enrollment_id": 1},
        ):
            if policy.get("enrollment_id") is not None:
                out.add(str(policy["enrollment_id"]))
        return out


def _optional_str(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _cents_value(
    doc: dict[str, Any],
    cents_keys: tuple[str, ...],
    money_keys: tuple[str, ...],
) -> int | None:
    for key in cents_keys:
        if doc.get(key) is not None:
            return int(doc[key])
    for key in money_keys:
        if doc.get(key) is not None:
            return int(round(float(doc[key]) * 100))
    return None
