"""One place that appends a ``PayoutAuditEntry`` (#787).

``PayoutAuditAction`` declares seven actions, but for a long time only the
three correction use cases in ``manage_payout_period`` ever wrote an entry —
generation, approval and payment, the transitions that actually move payroll
money, left no trace at all. Sharing one recorder between every payout use
case is what keeps that from drifting apart again: a use case that mutates a
period takes a recorder, and recording is the same two lines everywhere.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from backend.v2.contexts.finance.application.ports import PayoutAuditLog
from backend.v2.contexts.finance.domain.payout_audit import PayoutAuditEntry
from backend.v2.contexts.finance.domain.payout_period import PayoutPeriod
from backend.v2.shared.ids import new_ulid


class PayoutAuditRecorder:
    def __init__(
        self,
        *,
        audit: PayoutAuditLog,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._audit = audit
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id = id_factory or (lambda: str(new_ulid()))

    async def record(
        self,
        period: PayoutPeriod,
        *,
        action: str,
        actor_id: str,
        occurrence_id: str | None = None,
        reason: str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        await self._audit.append(
            PayoutAuditEntry(
                audit_id=self._id(),
                academy_id=period.academy_id,
                period_id=period.period_id,
                occurrence_id=occurrence_id,
                action=action,
                actor_id=actor_id,
                at=self._clock(),
                reason=reason,
                before=before,
                after=after,
            )
        )
