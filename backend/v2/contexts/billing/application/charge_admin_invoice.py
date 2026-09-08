"""The one audited path for an admin charging an invoice by hand.

Extracted from ``composition/admin.py`` so more than one surface can reuse it.
Before this module the flow lived inside the Billing Setup closure, so the
Family billing page (which replaced Billing Setup) charged through the bare
autopay use case: the attempt was recorded in Stripe as an unattributed
``autopay`` run and no ``admin_charge_initiated`` entry was written, which is
the entry the family timeline renders. The reason the admin typed went nowhere.

Two callers, one flow:

* Billing Setup / Family "Fix something" confirm dialog passes
  ``expected_amount_cents`` — the amount the admin was shown. A balance that
  moved underneath them aborts rather than charging a different number.
* Callers with no confirmed amount (the billing-health and reports lists) pass
  ``None`` and skip that guard; they still get attribution and the audit entry.

Application layer: every dependency arrives as a protocol, so there is no Mongo
or FastAPI import here.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.billing.domain.billing_audit import BillingAuditEntry

# A charge already submitted under this request is honoured rather than repeated
# if it landed within this window; past it the plan is assumed abandoned.
IN_FLIGHT_WINDOW = timedelta(seconds=60)


class IdempotencyStore(Protocol):
    async def get(self, key: str) -> dict[str, Any] | None: ...
    async def put(self, key: str, value: dict[str, Any]) -> None: ...


class SavedCardLookup(Protocol):
    async def has_saved_card(self, *, parent_id: str) -> bool: ...


class InvoiceLookup(Protocol):
    async def get_invoice(self, invoice_id: str) -> Any: ...


class AttemptLookup(Protocol):
    """Finds a prior payment attempt made under this same request id."""

    async def find_latest_attempt(
        self, *, academy_id: str, invoice_id: str, request_id: str
    ) -> dict[str, Any] | None: ...


class AuditLog(Protocol):
    async def append(self, entry: BillingAuditEntry) -> None: ...


class ChargeCallable(Protocol):
    async def __call__(
        self,
        invoice_id: str,
        *,
        source: str,
        actor_id: str | None,
        retry_scope: str | None,
    ) -> dict[str, Any]: ...


def attempt_regex(request_id: str) -> str:
    """Matches the terminal attempt statuses this request could have produced."""
    return f":{re.escape(request_id)}:(succeeded|processing|requires_action|failed):"


async def charge_invoice_as_admin(
    *,
    idempotency: IdempotencyStore,
    customers: SavedCardLookup,
    ledger: InvoiceLookup,
    attempts: AttemptLookup,
    charge: ChargeCallable,
    audit: AuditLog,
    academy_id: str,
    parent_id: str,
    invoice_id: str,
    actor_id: str,
    request_id: str,
    reason: str,
    source: str,
    audit_kind: str,
    idem_prefix: str,
    expected_amount_cents: int | None = None,
    clock: Any = None,
) -> dict[str, Any]:
    """Charge one invoice on an admin's instruction and record who and why.

    Raises ``ValueError`` with a machine-readable prefix the interfaces map to
    409s: ``no_saved_payment_method``, ``charge_target_changed``,
    ``charge_in_progress``.
    """
    now = clock or (lambda: datetime.now(UTC))
    scope = expected_amount_cents if expected_amount_cents is not None else "any"
    idem_key = f"admin_charge:{academy_id}:{actor_id}:{parent_id}:{invoice_id}:{scope}:{request_id}"
    result_key = f"{idem_key}:result"

    cached_result = await idempotency.get(result_key)
    payload: dict[str, Any] | None = cached_result["payload"] if cached_result else None

    if payload is None:
        if not await customers.has_saved_card(parent_id=parent_id):
            raise ValueError("no_saved_payment_method: parent has no saved card")
        invoice = await ledger.get_invoice(invoice_id)
        if invoice is None or invoice.parent_id != parent_id:
            raise ValueError("charge_target_changed: invoice is not available for this parent")

        created_plan = False
        plan = await idempotency.get(idem_key)
        if plan is None:
            plan = {"started_at": now().isoformat()}
            try:
                await idempotency.put(idem_key, plan)
                created_plan = True
            except DuplicateKeyError:
                plan = await idempotency.get(idem_key)
                if plan is None:
                    raise

        attempt = await attempts.find_latest_attempt(
            academy_id=academy_id, invoice_id=invoice_id, request_id=request_id
        )
        if not created_plan and attempt is None:
            started_at = datetime.fromisoformat(str(plan["started_at"]))
            if started_at > now() - IN_FLIGHT_WINDOW:
                raise ValueError("charge_in_progress: this charge is already being submitted")

        amount_moved = (
            expected_amount_cents is not None and invoice.balance_due_cents != expected_amount_cents
        )
        if amount_moved and attempt is None:
            raise ValueError("charge_target_changed: invoice balance changed; refresh and retry")

        if attempt is not None and (str(attempt.get("status")) != "succeeded" or amount_moved):
            attempt_status = str(attempt.get("status"))
            payload = {
                "invoice_id": invoice_id,
                "success": attempt_status == "succeeded",
                "status": invoice.status,
                "balance_due_cents": invoice.balance_due_cents,
                "charged_amount_cents": (
                    int(attempt.get("amount_cents") or 0) if attempt_status == "succeeded" else 0
                ),
                "attempted_amount_cents": int(attempt.get("amount_cents") or 0),
                "processing": attempt_status == "processing",
                "requires_action": attempt_status == "requires_action",
                "decline_code": attempt.get("failure_code"),
            }
        else:
            result = await charge(
                invoice_id, source=source, actor_id=actor_id, retry_scope=request_id
            )
            payload = dict(result)
            payload["charged_amount_cents"] = (
                int(result.get("attempted_amount_cents", 0)) if bool(result.get("success")) else 0
            )

        try:
            await idempotency.put(result_key, {"payload": payload})
        except DuplicateKeyError:
            cached_result = await idempotency.get(result_key)
            if cached_result is None:
                raise
            payload = cached_result["payload"]

    assert payload is not None

    await audit.append(
        BillingAuditEntry(
            audit_id=f"baud-{audit_kind}-{academy_id}-{invoice_id}-{request_id}",
            academy_id=academy_id,
            action="admin_charge_initiated",
            actor_id=actor_id,
            at=now(),
            invoice_id=invoice_id,
            parent_id=parent_id,
            reason=reason,
            before={"balance_due_cents": expected_amount_cents},
            after={
                "success": bool(payload["success"]),
                "status": str(payload["status"]),
                "balance_due_cents": int(payload["balance_due_cents"]),
                "attempted_amount_cents": int(payload["attempted_amount_cents"]),
            },
        )
    )
    return payload
