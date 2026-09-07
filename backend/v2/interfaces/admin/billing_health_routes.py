"""Admin BFF: the Billing Health page — Stripe plumbing, owner only.

Spec: ``docs/superpowers/specs/2026-09-07-billing-health-trim-design.md`` §5.

This page is the one you open when *Stripe* is the problem: money is not
arriving, a webhook is stuck, the connected account is not ready, a charge
exists in Stripe but not in the app. It carries nothing about a particular
family's payment behaviour — the Payments buckets and the Family billing page
own that — so every route here is governance and sits behind
:func:`require_owner`, alongside Reports and Payouts.

Services are attached at ``app.state.admin_billing_health`` by
``composition/billing_health.py`` (``composition/admin.py`` is at its line
budget). This module only knows their protocols.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from backend.v2.contexts.billing.application.ports import StripeResourceNotFound
from backend.v2.interfaces.admin.views import (
    BillingReconciliationReportResponse,
    BillingWebhookQueueResponse,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_owner


# --------------------------------------------------------------------------- #
# Services
# --------------------------------------------------------------------------- #
class AdminBillingHealthServices(Protocol):
    get_connect_readiness: Any
    list_reconciliation_runs: Any
    run_reconciliation: Any
    list_billing_webhook_events: Any
    replay_webhook_event: Any
    get_billing_reconciliation_report: Any
    confirm_legacy_match: Any


def get_admin_billing_health(request: Request) -> AdminBillingHealthServices:
    services: AdminBillingHealthServices = request.app.state.admin_billing_health
    return services


# --------------------------------------------------------------------------- #
# Views
# --------------------------------------------------------------------------- #
class ReconciliationRunDto(BaseModel):
    model_config = {"extra": "ignore"}

    run_id: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    scanned: int = 0
    repaired: int = 0
    skipped: int = 0
    quarantined: int = 0
    failed: int = 0
    errors: list[Any] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ReconciliationRunsResponse(BaseModel):
    runs: list[ReconciliationRunDto]


class ReplayWebhookResponse(BaseModel):
    replayed: bool
    event_id: str


class ConnectedAccountReadinessDto(BaseModel):
    model_config = {"extra": "ignore"}

    configured: bool = False
    status: str | None = None
    charges_enabled: bool = False
    payouts_enabled: bool = False
    ready_for_charges: bool = False
    account_id_masked: str | None = None


class WebhookBacklogDto(BaseModel):
    model_config = {"extra": "ignore"}

    quarantined: int = 0
    failed: int = 0


class HealthReasonDto(BaseModel):
    model_config = {"extra": "ignore"}

    code: str
    detail: str


class BillingHealthDto(BaseModel):
    """The one verdict (§4.2), composed on the backend.

    The page renders `state` and `headline` and computes nothing: the old
    page-side ``healthy`` flag read backlog counts alone and could show a green
    pill above a red "Parents cannot pay right now" card.
    """

    model_config = {"extra": "ignore"}

    state: str
    headline: str
    reasons: list[HealthReasonDto] = Field(default_factory=list)


class AutopayDisableFailureDto(BaseModel):
    model_config = {"extra": "ignore"}

    invoice_id: str
    parent_id: str
    error: str | None = None
    failed_at: datetime | None = None


class AutopayDisableFailuresDto(BaseModel):
    """Terminal autopay switch-offs the worker could not complete (§4.4)."""

    model_config = {"extra": "ignore"}

    count: int = 0
    rows: list[AutopayDisableFailureDto] = Field(default_factory=list)
    truncated: bool = False


class ConnectReadinessResponse(BaseModel):
    model_config = {"extra": "ignore"}

    connected_account: ConnectedAccountReadinessDto
    allow_platform_charge_fallback: bool = False
    #: Can a parent payment succeed at all right now.
    payments_possible: bool = False
    #: Whether a succeeding payment reaches the academy's own Stripe account
    #: rather than the platform's. `funds_route_to_academy` False while
    #: `payments_possible` is True means money is landing on the platform
    #: account through the fallback.
    funds_route_to_academy: bool = False
    webhook_events: WebhookBacklogDto
    autopay_disable_failures: AutopayDisableFailuresDto = Field(
        default_factory=AutopayDisableFailuresDto
    )
    health: BillingHealthDto


class ConfirmLegacyMatchRequest(BaseModel):
    invoice_id: str
    stripe_charge_id: str
    amount_cents: int = Field(gt=0)
    paid_at: datetime | None = None


class ConfirmLegacyMatchResponse(BaseModel):
    invoice_id: str
    payment_id: str
    invoice_status: str
    balance_due_cents: int


router = APIRouter(tags=["admin.billing_health"])


def _required(service: Any, label: str) -> Any:
    if service is None:
        raise HTTPException(status_code=503, detail=f"{label} is not configured")
    return service


# --------------------------------------------------------------------------- #
# Can parents pay?
# --------------------------------------------------------------------------- #
@router.get("/billing/connect-readiness", response_model=ConnectReadinessResponse)
async def get_connect_readiness(
    _claims: AuthClaims = Depends(require_owner()),
    services: AdminBillingHealthServices = Depends(get_admin_billing_health),
) -> ConnectReadinessResponse:
    """Whether parent payments can physically succeed, where money lands, and
    the single health verdict for the page header.

    This is the one fatal read on Billing Health: without it there is no
    verdict, so the page shows a retry panel rather than a misleading pill.
    """
    read = _required(services.get_connect_readiness, "Connect readiness")
    data = await read()
    return ConnectReadinessResponse(**data)


# --------------------------------------------------------------------------- #
# Webhooks
# --------------------------------------------------------------------------- #
@router.get("/billing/webhooks", response_model=BillingWebhookQueueResponse)
async def list_billing_webhook_events(
    status: str | None = None,
    limit: int = Query(default=50),
    _claims: AuthClaims = Depends(require_owner()),
    services: AdminBillingHealthServices = Depends(get_admin_billing_health),
) -> BillingWebhookQueueResponse:
    queue = _required(services.list_billing_webhook_events, "Billing webhook queue")
    rows = await queue(status=status, limit=max(1, min(limit, 100)))
    return BillingWebhookQueueResponse(events=rows)


@router.post(
    "/billing/webhook-events/{event_id}/replay",
    response_model=ReplayWebhookResponse,
)
async def replay_webhook_event(
    event_id: str,
    _claims: AuthClaims = Depends(require_owner()),
    services: AdminBillingHealthServices = Depends(get_admin_billing_health),
) -> ReplayWebhookResponse:
    replay = _required(services.replay_webhook_event, "Webhook replay")
    try:
        await replay(event_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ReplayWebhookResponse(replayed=True, event_id=event_id)


# --------------------------------------------------------------------------- #
# Reconciliation
# --------------------------------------------------------------------------- #
@router.get("/billing/reconciliation-runs", response_model=ReconciliationRunsResponse)
async def list_reconciliation_runs(
    _claims: AuthClaims = Depends(require_owner()),
    services: AdminBillingHealthServices = Depends(get_admin_billing_health),
) -> ReconciliationRunsResponse:
    list_runs = _required(services.list_reconciliation_runs, "Reconciliation runs")
    rows = await list_runs()
    return ReconciliationRunsResponse(runs=[ReconciliationRunDto(**r) for r in rows])


@router.post("/billing/reconcile-now", response_model=ReconciliationRunDto)
async def run_reconciliation_now(
    _claims: AuthClaims = Depends(require_owner()),
    services: AdminBillingHealthServices = Depends(get_admin_billing_health),
) -> ReconciliationRunDto:
    run = _required(services.run_reconciliation, "Reconciliation")
    try:
        result = await run()
    except RuntimeError as exc:
        # Stripe unconfigured — the button surfaces this message rather than a
        # generic failure (§7).
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ReconciliationRunDto(**result)


@router.get("/billing/reconciliation", response_model=BillingReconciliationReportResponse)
async def get_billing_reconciliation_report(
    stripe_invoice_id: str | None = None,
    payment_intent_id: str | None = None,
    _claims: AuthClaims = Depends(require_owner()),
    services: AdminBillingHealthServices = Depends(get_admin_billing_health),
) -> BillingReconciliationReportResponse:
    """Look one Stripe id up against the ledger. Read-only; changes nothing.

    Moved here from the Payments page (§5.2): it answers "Stripe says this
    happened — did we record it?", which is plumbing, not a family question.
    """
    if not stripe_invoice_id and not payment_intent_id:
        raise HTTPException(
            status_code=422,
            detail="stripe_invoice_id or payment_intent_id is required",
        )
    report = _required(services.get_billing_reconciliation_report, "Billing reconciliation report")
    try:
        result = await report(
            stripe_invoice_id=stripe_invoice_id,
            payment_intent_id=payment_intent_id,
        )
    except StripeResourceNotFound as exc:
        # str(exc) carries the raw provider error and the internal id — surface
        # a generic message instead.
        raise HTTPException(
            status_code=404,
            detail="That billing record could not be found. Check the ID and try again.",
        ) from exc
    return BillingReconciliationReportResponse(**result)


# --------------------------------------------------------------------------- #
# Link a Stripe charge to an invoice (the surviving half of legacy match)
# --------------------------------------------------------------------------- #
@router.post("/billing/legacy-match/confirm", response_model=ConfirmLegacyMatchResponse)
async def confirm_legacy_match(
    body: ConfirmLegacyMatchRequest,
    claims: AuthClaims = Depends(require_owner()),
    services: AdminBillingHealthServices = Depends(get_admin_billing_health),
) -> ConfirmLegacyMatchResponse:
    """Record a back-dated payment for a charge that only exists in Stripe.

    Idempotent on the (charge, invoice) pair, so a double submit is safe. It
    refuses an invoice that is not payable and an amount above the balance —
    both come back as 400 for the form to render inline.
    """
    confirm = _required(services.confirm_legacy_match, "Legacy match confirm")
    try:
        result = await confirm(
            invoice_id=body.invoice_id,
            stripe_charge_id=body.stripe_charge_id,
            amount_cents=body.amount_cents,
            paid_at=body.paid_at,
            recorded_by=claims.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ConfirmLegacyMatchResponse(**result)
