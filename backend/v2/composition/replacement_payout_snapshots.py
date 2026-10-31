"""Keep payout snapshots honest when an occurrence's coach changes (#787).

Swapping the coach on a dated class changes who gets paid for it, so any
payout period already holding that occurrence is wrong the moment the swap
lands. Two rules:

* An **approved or paid** period is frozen — the swap is refused outright,
  because payroll for that window is already committed.
* A **draft** period is *recomputed*, never deleted. Deleting the period (the
  old behaviour) dropped the ``payout_periods`` row while every
  ``payout_audit_log`` entry written for it stayed behind, pointing at a
  ``period_id`` that no longer resolved.

Lives outside ``composition/admin.py``: that module is at its structural
wiring budget, and this is logic rather than wiring.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.v2.contexts.finance.application.use_cases.manage_payout_period import (
    RecomputePayoutPeriod,
)

log = logging.getLogger(__name__)

FROZEN_PAYOUT_STATUSES = frozenset({"approved", "paid"})


async def draft_payout_periods_for_occurrence(
    db: Any,
    *,
    academy_id: str,
    occurrence_id: str,
) -> list[str]:
    """Ids of the draft periods holding this occurrence.

    Raises ``ValueError`` (409 at the route) when any holding period is
    already approved or paid.
    """
    line_cursor = db["payout_period_lines"].find(
        {"academy_id": academy_id, "occurrence_id": occurrence_id},
        {"period_id": 1},
    )
    period_ids = sorted(
        {str(row["period_id"]) async for row in line_cursor if row.get("period_id")}
    )
    if not period_ids:
        return []
    period_cursor = db["payout_periods"].find(
        {"academy_id": academy_id, "period_id": {"$in": period_ids}},
        {"period_id": 1, "status": 1},
    )
    draft_period_ids: list[str] = []
    async for period in period_cursor:
        if str(period.get("status") or "draft") in FROZEN_PAYOUT_STATUSES:
            raise ValueError("Replacement coach cannot be changed after payout is approved or paid")
        draft_period_ids.append(str(period["period_id"]))
    return draft_period_ids


async def recompute_draft_payout_periods(
    recompute: RecomputePayoutPeriod,
    *,
    period_ids: list[str],
    actor_id: str,
) -> None:
    """Refresh each draft period against the new coach assignment.

    Call this AFTER the occurrence write commits, so the recomputed snapshot
    reflects the change. Failures are logged, not raised: the coach change is
    already committed, and a stale draft is recoverable from the payroll
    screen while losing the change is not.
    """
    for period_id in period_ids:
        try:
            await recompute.execute(period_id=period_id, actor_id=actor_id)
        except Exception:  # pragma: no cover - best effort, post-commit
            log.warning(
                "payout_period_recompute_failed period_id=%s occurrence_change=replacement",
                period_id,
                exc_info=True,
            )
