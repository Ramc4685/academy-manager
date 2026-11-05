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

from pydantic import BaseModel, Field, field_validator

from backend.v2.contexts.billing.application.ports import BillingSettingsRepository
from backend.v2.contexts.billing.domain.billing_audit import BillingAuditEntry
from backend.v2.contexts.billing.domain.billing_settings import (
    APPLICATION_FEE_AGREEMENT_TEXT,
    APPLICATION_FEE_AGREEMENT_VERSION,
    MAX_APPLICATION_FEE_BPS,
    NEW_ACADEMY_APPLICATION_FEE_BPS,
    ApplicationFeeAgreementAcceptance,
    BillingSettings,
)
from backend.v2.contexts.billing.domain.errors import ApplicationFeeAcademyNotFound
from backend.v2.contexts.billing.domain.fees import application_fee_cents
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.tenancy import tenant_scope

log = logging.getLogger(__name__)

__all__ = [
    "APPLICATION_FEE_AGREEMENT_TEXT",
    "APPLICATION_FEE_AGREEMENT_VERSION",
    "MAX_APPLICATION_FEE_BPS",
    "NEW_ACADEMY_APPLICATION_FEE_BPS",
    "AgreementAcceptance",
    "ApplicationFeeResult",
    "AssignDefaultApplicationFee",
    "GetApplicationFee",
    "ReadAcademyApplicationFee",
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
    # The processing-fee agreement: the current text and version (from code)
    # and the acceptance recorded with the fee, if any.
    agreement_version: str | None = None
    agreement_text: str = APPLICATION_FEE_AGREEMENT_TEXT
    current_agreement_version: str = APPLICATION_FEE_AGREEMENT_VERSION
    accepted_at: datetime | None = None
    accepted_by: str | None = None


def _result(academy_id: str, settings: BillingSettings) -> ApplicationFeeResult:
    return ApplicationFeeResult(
        academy_id=academy_id,
        application_fee_bps=settings.application_fee_bps,
        agreement_version=settings.application_fee_agreement_version,
        accepted_at=settings.application_fee_accepted_at,
        accepted_by=settings.application_fee_accepted_by,
    )


def _agreement_fields(settings: BillingSettings) -> dict[str, Any]:
    return {
        "application_fee_bps": settings.application_fee_bps,
        "application_fee_agreement_version": settings.application_fee_agreement_version,
        "application_fee_accepted_at": settings.application_fee_accepted_at,
        "application_fee_accepted_by": settings.application_fee_accepted_by,
    }


class AgreementAcceptance(BaseModel):
    """The academy signatory, as typed by the platform admin, accepting the
    agreement version the admin was shown. Only the current version can be
    recorded, so the stored version always names a text that exists."""

    model_config = {"frozen": True}

    version: str = Field(min_length=1)
    accepted_by: str = Field(min_length=1)

    @field_validator("version")
    @classmethod
    def _current_version_only(cls, value: str) -> str:
        if value != APPLICATION_FEE_AGREEMENT_VERSION:
            raise ValueError(
                f"unknown agreement version; current is {APPLICATION_FEE_AGREEMENT_VERSION}"
            )
        return value


class SetApplicationFeeCommand(BaseModel):
    model_config = {"frozen": True}

    academy_id: str = Field(min_length=1)
    application_fee_bps: int = Field(ge=0, le=MAX_APPLICATION_FEE_BPS)
    actor_id: str = Field(min_length=1)
    reason: str | None = None
    agreement: AgreementAcceptance | None = None


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
        return _result(academy_id, current)


class ReadAcademyApplicationFee:
    """The CURRENT academy's fee and agreement, for the academy admin's
    read-only view (``GET /admin/billing/platform-fee``). Tenant from scope."""

    def __init__(self, *, settings: BillingSettingsRepository) -> None:
        self._settings = settings

    async def execute(self) -> ApplicationFeeResult:
        current = await self._settings.get()
        return _result(current.academy_id, current)


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
        now = self._now()
        acceptance = (
            ApplicationFeeAgreementAcceptance(
                version=cmd.agreement.version,
                accepted_by=cmd.agreement.accepted_by,
                accepted_at=now,
            )
            if cmd.agreement is not None
            else None
        )
        with tenant_scope(cmd.academy_id):
            current = await self._settings.get()
            same_acceptance = acceptance is None or (
                acceptance.version == current.application_fee_agreement_version
                and acceptance.accepted_by == current.application_fee_accepted_by
            )
            if current.application_fee_bps == cmd.application_fee_bps and same_acceptance:
                return _result(cmd.academy_id, current)
            after = current.model_copy(
                update={
                    "application_fee_bps": cmd.application_fee_bps,
                    **(
                        {
                            "application_fee_agreement_version": acceptance.version,
                            "application_fee_accepted_at": acceptance.accepted_at,
                            "application_fee_accepted_by": acceptance.accepted_by,
                        }
                        if acceptance is not None
                        else {}
                    ),
                }
            )
            if self._audit is not None:
                await self._audit.append(
                    BillingAuditEntry(
                        audit_id=f"baud-{new_ulid()}",
                        academy_id=cmd.academy_id,
                        action="application_fee_changed",
                        actor_id=cmd.actor_id,
                        at=now,
                        reason=cmd.reason,
                        before=_agreement_fields(current),
                        after=_agreement_fields(after),
                    )
                )
            await self._settings.set_application_fee_bps(
                cmd.application_fee_bps, agreement=acceptance
            )
        log.info(
            "application_fee: academy=%s fee_bps %s -> %s by actor=%s",
            cmd.academy_id,
            current.application_fee_bps,
            cmd.application_fee_bps,
            cmd.actor_id,
        )
        return _result(cmd.academy_id, after)


class AssignDefaultApplicationFee:
    """Start a NEWLY CREATED academy on the default processing markup
    (``NEW_ACADEMY_APPLICATION_FEE_BPS``), with no agreement acceptance yet.

    Platform's ``TenantLifecycleService.create_tenant`` calls this through its
    ``DefaultApplicationFeeAssigner`` port, exactly like the invoice prefix.
    Audited as an ordinary fee change by the creating platform admin.
    Idempotent through ``SetApplicationFee``: re-running on an academy already
    at the default writes nothing.
    """

    def __init__(self, *, set_fee: SetApplicationFee) -> None:
        self._set_fee = set_fee

    async def execute(self, *, academy_id: str, actor_id: str) -> int:
        await self._set_fee.execute(
            SetApplicationFeeCommand(
                academy_id=academy_id,
                application_fee_bps=NEW_ACADEMY_APPLICATION_FEE_BPS,
                actor_id=actor_id,
                reason="default for new academies",
            )
        )
        log.info(
            "application_fee_default_assigned academy=%s fee_bps=%s",
            academy_id,
            NEW_ACADEMY_APPLICATION_FEE_BPS,
        )
        return NEW_ACADEMY_APPLICATION_FEE_BPS
