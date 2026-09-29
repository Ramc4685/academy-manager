"""Audit trail for owner-only money settings edited outside Billing rules.

Settings overhaul Phase 1 PR 5 made a class's monthly fee and the academy
timezone owner-only. Both are edited on mixed forms (the class form, the
Academy panel) whose other fields stay admin work, so there is no dedicated
billing use case to write the trail. This one appends to the same
``billing_audit_log`` every Billing rules change already lands in; it adds no
new store or mechanism.

Best effort by design: the setting has already been written when this runs,
so an audit failure is logged and swallowed rather than turned into a 500 that
would invite a retry of a write that already landed (same rule as
``UpdateBillingRules._audit_best_effort``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from backend.v2.contexts.billing.application.use_cases.billing_settings_admin import (
    BillingAuditAppender,
)
from backend.v2.contexts.billing.domain.billing_audit import BillingAuditEntry
from backend.v2.shared.ids import new_ulid

log = logging.getLogger(__name__)

MoneySettingAction = Literal[
    "session_fee_changed",
    "academy_timezone_changed",
    "class_plan_link_changed",
    "class_plan_links_matched",
]


class RecordMoneySettingChange:
    """Append one ``billing_audit_log`` entry for an owner money-setting change."""

    def __init__(
        self,
        *,
        audit: BillingAuditAppender,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._audit = audit
        self._now = now or (lambda: datetime.now(UTC))

    async def execute(
        self,
        *,
        academy_id: str,
        action: MoneySettingAction,
        actor_id: str,
        before: dict[str, Any],
        after: dict[str, Any],
        reason: str | None = None,
    ) -> bool:
        """Return ``True`` when the entry landed, ``False`` when it did not."""
        if before == after:
            return True
        try:
            await self._audit.append(
                BillingAuditEntry(
                    audit_id=f"baud-{new_ulid()}",
                    academy_id=academy_id,
                    action=action,
                    actor_id=actor_id,
                    at=self._now(),
                    reason=reason,
                    before=before,
                    after=after,
                )
            )
        except Exception:
            log.exception(
                "money_setting_audit_failed",
                extra={"academy_id": academy_id, "action": action, "actor_id": actor_id},
            )
            return False
        return True
