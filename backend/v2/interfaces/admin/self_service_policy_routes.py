"""Admin routes for the per-academy parent self-service policy."""

from __future__ import annotations

from typing import Final, Literal, Protocol

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.v2.contexts.enrollment.application.use_cases.self_service_policies import (
    UpdateSelfServicePolicyCommand,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.owner_gate import ensure_owner_for_payment_instructions
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.self-service"])


class _PolicyLike(Protocol):
    """Shape of ParentSelfServicePolicy, referenced structurally.

    Interface modules never import domain types directly (ADR-0006 import
    boundaries) — the use case returns the domain model, and this route only
    relies on its attributes.
    """

    absence_notice_min_hours: int
    makeup_expiry_days: int
    makeup_requires_notice: bool
    cancellation_minimum_notice_days: int
    cancellation_fee_cents: int
    cancellation_effective_timing: Literal["immediate", "end_of_period"]
    can_report_absence: bool
    can_request_makeup: bool
    can_request_pause: bool
    can_request_cancel: bool
    can_claim_waitlist_offer: bool
    payment_instructions: str


class SelfServicePolicyView(BaseModel):
    absence_notice_min_hours: int
    makeup_expiry_days: int
    makeup_requires_notice: bool
    cancellation_minimum_notice_days: int
    cancellation_fee_cents: int
    cancellation_effective_timing: Literal["immediate", "end_of_period"]
    can_report_absence: bool
    can_request_makeup: bool
    can_request_pause: bool
    can_request_cancel: bool
    can_claim_waitlist_offer: bool
    payment_instructions: str

    @staticmethod
    def from_domain(policy: _PolicyLike) -> SelfServicePolicyView:
        return SelfServicePolicyView(
            absence_notice_min_hours=policy.absence_notice_min_hours,
            makeup_expiry_days=policy.makeup_expiry_days,
            makeup_requires_notice=policy.makeup_requires_notice,
            cancellation_minimum_notice_days=policy.cancellation_minimum_notice_days,
            cancellation_fee_cents=policy.cancellation_fee_cents,
            cancellation_effective_timing=policy.cancellation_effective_timing,
            can_report_absence=policy.can_report_absence,
            can_request_makeup=policy.can_request_makeup,
            can_request_pause=policy.can_request_pause,
            can_request_cancel=policy.can_request_cancel,
            can_claim_waitlist_offer=policy.can_claim_waitlist_offer,
            payment_instructions=policy.payment_instructions,
        )


class UpdateSelfServicePolicyRequest(BaseModel):
    """Any subset of the six fields; only the ones sent are written.

    The Settings page sends just the fields the admin changed. An older
    client that still sends all six is fine: a field equal to the stored value
    is not a change.

    The cancellation fee and notice are accepted only so that such a client
    keeps working: Billing rules is their one write path (Settings overhaul
    Phase 1 PR 5), so a changed value here is refused, owner or not.
    """

    absence_notice_min_hours: int | None = Field(default=None, ge=0)
    makeup_expiry_days: int | None = Field(default=None, ge=1)
    makeup_requires_notice: bool | None = None
    cancellation_minimum_notice_days: int | None = Field(default=None, ge=0)
    cancellation_fee_cents: int | None = Field(default=None, ge=0)
    cancellation_effective_timing: Literal["immediate", "end_of_period"] | None = None
    can_report_absence: bool | None = None
    can_request_makeup: bool | None = None
    can_request_pause: bool | None = None
    can_request_cancel: bool | None = None
    can_claim_waitlist_offer: bool | None = None
    payment_instructions: str | None = Field(default=None, max_length=1000)


#: The two fields Billing rules owns. Self-service shows neither any more.
CANCELLATION_TERMS: Final[tuple[str, ...]] = (
    "cancellation_minimum_notice_days",
    "cancellation_fee_cents",
)

CANCELLATION_TERMS_MOVED: Final[str] = (
    "The cancellation fee and notice are set in Settings -> Billing rules."
)


@router.get("/self-service/policy", response_model=SelfServicePolicyView)
async def get_self_service_policy(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> SelfServicePolicyView:
    policy = await use_cases.self_service_policy.execute()
    return SelfServicePolicyView.from_domain(policy)


@router.put("/self-service/policy", response_model=SelfServicePolicyView)
async def update_self_service_policy(
    body: UpdateSelfServicePolicyRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> SelfServicePolicyView:
    reader = use_cases.self_service_policy
    writer = use_cases.update_self_service_policy
    if reader is None or writer is None:
        raise RuntimeError("self-service policy use cases are not wired on AdminUseCases")
    requested = body.model_dump(exclude_none=True)
    current = await reader.execute()
    changed_terms = [
        key
        for key in CANCELLATION_TERMS
        if key in requested and requested[key] != getattr(current, key)
    ]
    if changed_terms:
        # Money audit X5 routed these through Billing rules from here; the
        # Settings overhaul (Phase 1 PR 5) removes the second write path
        # entirely. Nothing is written, not even the other fields sent.
        raise HTTPException(
            status_code=422,
            detail={"field": changed_terms[0], "message": CANCELLATION_TERMS_MOVED},
        )
    others = {key: value for key, value in requested.items() if key not in CANCELLATION_TERMS}

    if (
        "payment_instructions" in others
        and others["payment_instructions"] == current.payment_instructions
    ):
        del others["payment_instructions"]
    elif "payment_instructions" in others:
        # Payment instructions are owner-only content shown to parents
        # (Lane C, 2026-09-29 owner decision): only refuse when the value is
        # actually changing.
        ensure_owner_for_payment_instructions(claims)

    if others:
        await writer.execute(UpdateSelfServicePolicyCommand(**others))
    return SelfServicePolicyView.from_domain(await reader.execute())
