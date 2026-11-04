"""Settings -> Billing rules -> Offline payments: one owner-only, audited write.

``academies.manual_methods`` decides which offline methods (cash, check,
Zelle...) the admin payment dialogs offer. The value lives on the academy
record (identity); this use case owns the money-setting rules around it:
validation against billing's ``ManualPaymentMethod`` set, at least one method,
and one ``payment_methods_changed`` audit entry per real change. The identity
reader and writer arrive as narrow ports wired in
``composition/payment_methods.py``, so nothing here imports another context.

Recording a payment is deliberately NOT checked against this list yet:
``RecordManualPayment`` still accepts all six, so an old open dialog or a
back-office correction is never blocked (settings overhaul Phase 4).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final, Protocol, get_args

from pydantic import BaseModel, Field

from backend.v2.contexts.billing.application.use_cases.billing_settings_admin import (
    BillingAuditAppender,
)
from backend.v2.contexts.billing.application.use_cases.record_manual_payment import (
    ManualPaymentMethod,
)
from backend.v2.contexts.billing.domain.billing_audit import BillingAuditEntry
from backend.v2.shared.ids import new_ulid

log = logging.getLogger(__name__)

#: Canonical order: the order the dialogs have always listed them in.
MANUAL_PAYMENT_METHODS: Final[tuple[str, ...]] = get_args(ManualPaymentMethod)


class ManualPaymentMethodsValidationError(ValueError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.field = "manual_methods"
        self.message = message


class ManualMethodsReader(Protocol):
    async def execute(self, academy_id: str) -> list[str]: ...


class ManualMethodsWriter(Protocol):
    async def execute(self, academy_id: str, methods: list[str], *, actor_id: str) -> list[str]: ...


class UpdateManualPaymentMethodsCommand(BaseModel):
    model_config = {"frozen": True}

    manual_methods: list[str]
    actor_id: str = Field(min_length=1)
    reason: str | None = None


class UpdateManualPaymentMethods:
    def __init__(
        self,
        *,
        reader: ManualMethodsReader,
        writer: ManualMethodsWriter,
        audit: BillingAuditAppender | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._audit = audit
        self._now = clock

    async def execute(self, academy_id: str, cmd: UpdateManualPaymentMethodsCommand) -> list[str]:
        chosen = _validate(cmd.manual_methods)
        before = await self._reader.execute(academy_id)
        if chosen == before:
            return before
        after = await self._writer.execute(academy_id, chosen, actor_id=cmd.actor_id)
        await self._audit_best_effort(academy_id, cmd, before, after)
        return after

    async def _audit_best_effort(
        self,
        academy_id: str,
        cmd: UpdateManualPaymentMethodsCommand,
        before: list[str],
        after: list[str],
    ) -> None:
        """Same rule as Billing rules: an audit failure never hides the write."""
        if self._audit is None:
            return
        try:
            await self._audit.append(
                BillingAuditEntry(
                    audit_id=f"baud-{new_ulid()}",
                    academy_id=academy_id,
                    action="payment_methods_changed",
                    actor_id=cmd.actor_id,
                    at=self._now(),
                    reason=cmd.reason,
                    before={"manual_methods": before},
                    after={"manual_methods": after},
                )
            )
        except Exception:
            log.error(
                "payment_methods_audit_failed",
                exc_info=True,
                extra={"academy_id": academy_id},
            )


def _validate(methods: list[str]) -> list[str]:
    unknown = sorted({m for m in methods if m not in MANUAL_PAYMENT_METHODS})
    if unknown:
        raise ManualPaymentMethodsValidationError(f"Unknown payment method: {', '.join(unknown)}.")
    chosen = [m for m in MANUAL_PAYMENT_METHODS if m in methods]
    if not chosen:
        raise ManualPaymentMethodsValidationError("Keep at least one offline payment method.")
    return chosen
