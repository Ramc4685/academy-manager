"""Admin Billing Setup routes — Stripe registration status, invite, charge, autopay.

Shows which paying parents can be charged today (card on file), which have an
account but no card, and which have no login account at all — with a
context-aware invite action, a one-off "charge now", and "enable autopay"
across a parent's eligible children.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.v2.contexts.billing.application.use_cases.billing_setup_registration import (
    BillingSetupPage,
    BillingSetupRow,
    RegistrationState,
)
from backend.v2.contexts.identity.application.use_cases.provision_parent_login import (
    ProvisionParentLoginCommand,
)
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.billing.setup"])
log = logging.getLogger(__name__)
_PUBLIC_ERROR_CODE = re.compile(r"^[a-z0-9_]{1,64}$")


def _public_failure(value: str | None, fallback: str) -> str:
    candidate = (value or "").strip().lower()
    return candidate if _PUBLIC_ERROR_CODE.fullmatch(candidate) else fallback


def _required_callable(use_case: object | None, name: str) -> object:
    if use_case is None:
        raise HTTPException(status_code=503, detail=f"{name} is not configured")
    return use_case


class BillingSetupStudentDto(BaseModel):
    student_id: str
    full_name: str


class BillingSetupRowDto(BaseModel):
    parent_id: str
    parent_name: str
    parent_email: str | None = None
    students: list[BillingSetupStudentDto]
    registration_state: RegistrationState
    card_label: str | None = None
    card_last4: str | None = None
    autopay_active_count: int
    autopay_eligible_count: int
    outstanding_balance_cents: int
    charge_invoice_id: str | None = None
    charge_amount_cents: int = 0
    charge_autopay_eligible: bool = False
    last_invited_at: datetime | None = None


class BillingSetupSummaryDto(BaseModel):
    families_total: int
    families_registered: int
    families_no_card: int
    outstanding_total_cents: int


class BillingSetupPageResponse(BaseModel):
    rows: list[BillingSetupRowDto]
    summary: BillingSetupSummaryDto
    next_cursor: str | None = None


def _to_response(page: BillingSetupPage) -> BillingSetupPageResponse:
    return BillingSetupPageResponse(
        rows=[
            BillingSetupRowDto(
                parent_id=row.parent_id,
                parent_name=row.parent_name,
                parent_email=row.parent_email,
                students=[
                    BillingSetupStudentDto(student_id=s.student_id, full_name=s.full_name)
                    for s in row.students
                ],
                registration_state=row.registration_state,
                card_label=row.card_label,
                card_last4=row.card_last4,
                autopay_active_count=row.autopay_active_count,
                autopay_eligible_count=row.autopay_eligible_count,
                outstanding_balance_cents=row.outstanding_balance_cents,
                charge_invoice_id=row.charge_invoice_id,
                charge_amount_cents=row.charge_amount_cents,
                charge_autopay_eligible=row.charge_autopay_eligible,
                last_invited_at=row.last_invited_at,
            )
            for row in page.rows
        ],
        summary=BillingSetupSummaryDto(
            families_total=page.summary.families_total,
            families_registered=page.summary.families_registered,
            families_no_card=page.summary.families_no_card,
            outstanding_total_cents=page.summary.outstanding_total_cents,
        ),
        next_cursor=page.next_cursor,
    )


@router.get("/billing/setup", response_model=BillingSetupPageResponse)
async def list_billing_setup(
    status: Literal["all", "no_account", "account_no_card", "card_on_file"] = "all",
    q: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> BillingSetupPageResponse:
    list_use_case = _required_callable(use_cases.list_billing_setup, "Billing Setup")
    page = await list_use_case.execute(  # type: ignore[attr-defined]
        academy_id=claims.academy_id,
        status_filter=status,
        q=q,
        cursor=cursor,
        limit=limit,
    )
    return _to_response(page)


class BillingSetupInviteResponse(BaseModel):
    action: Literal["login_invite", "add_card_reminder", "not_applicable"]
    ok: bool
    failed_reason: str | None = None
    invited_at: datetime | None = None


async def _find_row(
    use_cases: AdminUseCases, parent_id: str, *, academy_id: str
) -> BillingSetupRow:
    list_use_case = _required_callable(use_cases.list_billing_setup, "Billing Setup")
    page = await list_use_case.execute(  # type: ignore[attr-defined]
        academy_id=academy_id, parent_id=parent_id, limit=1
    )
    if page.rows:
        return cast(BillingSetupRow, page.rows[0])
    raise HTTPException(status_code=404, detail=f"parent {parent_id!r} not found")


@router.post("/billing/setup/{parent_id}/invite", response_model=BillingSetupInviteResponse)
async def invite_billing_setup_parent(
    parent_id: str,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> BillingSetupInviteResponse:
    row = await _find_row(use_cases, parent_id, academy_id=claims.academy_id)

    if row.registration_state == "card_on_file":
        return BillingSetupInviteResponse(action="not_applicable", ok=True)

    record_invite = _required_callable(
        use_cases.record_billing_setup_invite, "Billing Setup invite tracking"
    )

    if row.registration_state == "no_account":
        if not row.parent_email:
            return BillingSetupInviteResponse(
                action="login_invite", ok=False, failed_reason="parent_email_missing"
            )
        provision = _required_callable(
            use_cases.provision_parent_login, "Parent login provisioning"
        )
        send_login_invite = _required_callable(use_cases.send_login_invite, "Login invite")
        try:
            login_user_id = await provision.execute(  # type: ignore[attr-defined]
                ProvisionParentLoginCommand(
                    parent_id=parent_id,
                    email=row.parent_email,
                    display_name=row.parent_name,
                    actor_id=claims.user_id,
                ),
                academy_id=claims.academy_id,
            )
            result = await send_login_invite.execute(  # type: ignore[attr-defined]
                login_user_id, academy_id=claims.academy_id
            )
        except Exception:
            log.exception("Billing Setup login invite failed parent_id=%s", parent_id)
            return BillingSetupInviteResponse(
                action="login_invite", ok=False, failed_reason="login_invite_failed"
            )
        invited_at = await record_invite(parent_id)  # type: ignore[operator]
        return BillingSetupInviteResponse(
            action="login_invite", ok=True, invited_at=invited_at or result.sent_at
        )

    send_reminder = _required_callable(use_cases.send_add_card_reminder, "Add-card reminder")
    try:
        outcome = await send_reminder.execute(  # type: ignore[attr-defined]
            academy_id=claims.academy_id, parent_id=parent_id
        )
    except Exception:
        log.exception("Billing Setup add-card reminder failed parent_id=%s", parent_id)
        return BillingSetupInviteResponse(
            action="add_card_reminder", ok=False, failed_reason="add_card_reminder_failed"
        )
    if not outcome.ok:
        return BillingSetupInviteResponse(
            action="add_card_reminder",
            ok=False,
            failed_reason=_public_failure(outcome.failed_reason, "email_delivery_failed"),
        )
    invited_at = await record_invite(parent_id)  # type: ignore[operator]
    return BillingSetupInviteResponse(action="add_card_reminder", ok=True, invited_at=invited_at)


class BillingSetupChargeResponse(BaseModel):
    invoice_id: str
    success: bool
    status: str
    balance_due_cents: int
    charged_amount_cents: int = 0
    attempted_amount_cents: int = 0
    processing: bool = False
    requires_action: bool = False
    decline_code: str | None = None


class BillingSetupChargeRequest(BaseModel):
    invoice_id: str = Field(min_length=1, max_length=120)
    expected_amount_cents: int = Field(gt=0)
    request_id: str = Field(min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


@router.post("/billing/setup/{parent_id}/charge", response_model=BillingSetupChargeResponse)
async def charge_billing_setup_parent(
    parent_id: str,
    payload: BillingSetupChargeRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> BillingSetupChargeResponse:
    charge = _required_callable(use_cases.charge_billing_setup_balance, "Billing Setup charge")
    try:
        result = await charge(  # type: ignore[operator]
            parent_id=parent_id,
            invoice_id=payload.invoice_id,
            expected_amount_cents=payload.expected_amount_cents,
            request_id=payload.request_id,
            actor_id=claims.user_id,
        )
    except ValueError as exc:
        code = _public_failure(str(exc).split(":", 1)[0], "charge_request_invalid")
        raise HTTPException(status_code=400, detail=code) from exc
    except RuntimeError as exc:
        log.exception("Billing Setup charge unavailable parent_id=%s", parent_id)
        raise HTTPException(status_code=503, detail="payment_service_unavailable") from exc
    return BillingSetupChargeResponse(
        invoice_id=str(result["invoice_id"]),
        success=bool(result["success"]),
        status=str(result["status"]),
        balance_due_cents=int(result["balance_due_cents"]),
        charged_amount_cents=int(result.get("charged_amount_cents", 0)),
        attempted_amount_cents=int(result.get("attempted_amount_cents", 0)),
        processing=bool(result.get("processing", False)),
        requires_action=bool(result.get("requires_action", False)),
        decline_code=_public_failure(result.get("decline_code"), "payment_declined")
        if result.get("decline_code")
        else None,
    )


class BillingSetupAutopayEnableResponse(BaseModel):
    eligible_count: int
    enabled_count: int


class BillingSetupAutopayEnableRequest(BaseModel):
    request_id: str = Field(min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


@router.post(
    "/billing/setup/{parent_id}/autopay/enable",
    response_model=BillingSetupAutopayEnableResponse,
)
async def enable_billing_setup_autopay(
    parent_id: str,
    payload: BillingSetupAutopayEnableRequest,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> BillingSetupAutopayEnableResponse:
    enable = _required_callable(
        use_cases.enable_billing_setup_autopay, "Billing Setup autopay enable"
    )
    try:
        result = await enable(  # type: ignore[operator]
            parent_id=parent_id,
            actor_id=claims.user_id,
            request_id=payload.request_id,
        )
    except ValueError as exc:
        code = _public_failure(str(exc).split(":", 1)[0], "autopay_request_invalid")
        raise HTTPException(status_code=400, detail=code) from exc
    return BillingSetupAutopayEnableResponse(
        eligible_count=int(result["eligible_count"]),
        enabled_count=int(result["enabled_count"]),
    )
