"""Audit trail for payout-period mutations.

Every admin action that creates or changes a payout period writes one
immutable entry: who did it, when, what changed (before/after snapshots
of the affected fields), and why. The trail is the backbone of the
"admin can correct past payroll" workflow — periods can be reopened and
recomputed precisely because every step is recorded.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

PayoutAuditAction = Literal[
    "generated",
    "recomputed",
    "reopened",
    "approved",
    "marked_paid",
    "line_overridden",
    "line_override_cleared",
]


class PayoutAuditEntry(BaseModel):
    model_config = {"frozen": True}

    audit_id: str
    academy_id: str
    period_id: str
    occurrence_id: str | None = None
    action: PayoutAuditAction
    actor_id: str
    at: datetime
    reason: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
