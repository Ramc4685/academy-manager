"""Per-academy platform application fee (roadmap L9b).

The fee is stored on the academy's ``billing_settings`` as basis points
(``application_fee_bps``, default 0) and turned into Stripe's
``application_fee_amount`` per destination charge by
``domain.fees.application_fee_cents`` (floor rounding, never more than the
charge).

Only a platform admin can change it: ``SetApplicationFee`` is wired to the
platform BFF alone, and the academy-side settings write
(``BillingSettingsRepository.upsert``) never persists the field.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field

from backend.v2.contexts.billing.application.ports import BillingSettingsRepository
from backend.v2.contexts.billing.domain.billing_audit import BillingAuditEntry
from backend.v2.contexts.billing.domain.billing_settings import MAX_APPLICATION_FEE_BPS
from backend.v2.contexts.billing.domain.errors import ApplicationFeeAcademyNotFound
from backend.v2.contexts.billing.domain.fees import application_fee_cents
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import tenant_scope

log = logging.getLogger(__name__)

__all__ = [
    "MAX_APPLICATION_FEE_BPS",
    "ApplicationFeeResult",
    "GetApplicationFee",
    "SetApplicationFee",
    "SetApplicationFeeCommand",
    "application_fee_kwargs",
    "idempotency_key_with_fee",
    "resolve_application_fee_cents",
]


# ---------------------------------------------------------------------------
# Charge-time resolution (used by every destination-charge call site)
# ---------------------------------------------------------------------------


async def resolve_application_fee_cents(
    settings: BillingSettingsRepository | None,
    *,
    amount_cents: int,
    connected_account_id: str | None,
) -> int:
    """The current academy's platform fee for one charge, in cents.

    Zero unless the charge is a destination charge to a connected account. A
    settings lookup failure charges with NO fee (logged as an error) rather
    than blocking the parent's payment: the academy then keeps the whole
    charge, which is the pre-L9b behaviour.
    """
    if not connected_account_id or settings is None or amount_cents <= 0:
        return 0
    try:
        current = await settings.get()
    except Exception as exc:
        log.error(
            "application_fee: billing settings lookup failed; charging with no platform fee err=%s",
            exc,
        )
        return 0
    return application_fee_cents(amount_cents, int(getattr(current, "application_fee_bps", 0)))


def application_fee_kwargs(fee_cents: int) -> dict[str, Any]:
    """Gateway kwargs for a fee: empty for 0, so a zero-fee call stays
    byte-identical to the pre-L9b one (and older narrow test gateways keep
    working)."""
    return {"application_fee_cents": fee_cents} if fee_cents else {}


def idempotency_key_with_fee(key: str, fee_cents: int) -> str:
    """Scope a Stripe idempotency key to the fee.

    Stripe rejects a replayed key whose params differ, so a fee change inside
    the idempotency window would otherwise turn the retry into an error. A
    zero fee leaves the key exactly as before.
    """
    return f"{key}:fee{fee_cents}" if fee_cents else key


# ---------------------------------------------------------------------------
# Platform-admin read / write
# ---------------------------------------------------------------------------


class BillingAuditAppender(Protocol):
    async def append(self, entry: BillingAuditEntry) -> None: ...


AcademyExists = Callable[[str], Awaitable[bool]]


class ApplicationFeeResult(BaseModel):
    model_config = {"frozen": True}

    academy_id: str
    application_fee_bps: int
    max_application_fee_bps: int = MAX_APPLICATION_FEE_BPS


class SetApplicationFeeCommand(BaseModel):
    model_config = {"frozen": True}

    academy_id: str = Field(min_length=1)
    application_fee_bps: int = Field(ge=0, le=MAX_APPLICATION_FEE_BPS)
    actor_id: str = Field(min_length=1)
    reason: str | None = None


class GetApplicationFee:
    def __init__(
        self,
        *,
        settings: BillingSettingsRepository,
        academy_exists: AcademyExists | None = None,
    ) -> None:
        self._settings = settings
        self._academy_exists = academy_exists

    async def execute(self, academy_id: str) -> ApplicationFeeResult:
        if self._academy_exists is not None and not await self._academy_exists(academy_id):
            raise ApplicationFeeAcademyNotFound("academy not found", academy_id=academy_id)
        with tenant_scope(academy_id):
            current = await self._settings.get()
        return ApplicationFeeResult(
            academy_id=academy_id, application_fee_bps=current.application_fee_bps
        )


class SetApplicationFee:
    """Set one academy's application fee, with an append-only audit entry.

    Idempotent: writing the current value is a no-op with no audit entry.
    The audit is written BEFORE the settings write so the fee can never
    change unaudited; a failed write leaves an intent record, not a gap.
    """

    def __init__(
        self,
        *,
        settings: BillingSettingsRepository,
        audit: BillingAuditAppender | None = None,
        academy_exists: AcademyExists | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._settings = settings
        self._audit = audit
        self._academy_exists = academy_exists
        self._now = clock

    async def execute(self, cmd: SetApplicationFeeCommand) -> ApplicationFeeResult:
        if self._academy_exists is not None and not await self._academy_exists(cmd.academy_id):
            raise ApplicationFeeAcademyNotFound("academy not found", academy_id=cmd.academy_id)
        with tenant_scope(cmd.academy_id):
            current = await self._settings.get()
            if current.application_fee_bps == cmd.application_fee_bps:
                return ApplicationFeeResult(
                    academy_id=cmd.academy_id, application_fee_bps=cmd.application_fee_bps
                )
            if self._audit is not None:
                await self._audit.append(
                    BillingAuditEntry(
                        audit_id=f"baud-{new_ulid()}",
                        academy_id=cmd.academy_id,
                        action="application_fee_changed",
                        actor_id=cmd.actor_id,
                        at=self._now(),
                        reason=cmd.reason,
                        before={"application_fee_bps": current.application_fee_bps},
                        after={"application_fee_bps": cmd.application_fee_bps},
                    )
                )
            await self._settings.set_application_fee_bps(cmd.application_fee_bps)
        log.info(
            "application_fee: academy=%s fee_bps %s -> %s by actor=%s",
            cmd.academy_id,
            current.application_fee_bps,
            cmd.application_fee_bps,
            cmd.actor_id,
        )
        return ApplicationFeeResult(
            academy_id=cmd.academy_id, application_fee_bps=cmd.application_fee_bps
        )
