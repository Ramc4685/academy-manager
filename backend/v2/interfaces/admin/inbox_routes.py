"""Admin unified inbox routes (issue #776).

The eight approval queues an academy actually works through — three admissions
queues and five parent-request queues — used to live on two pages with plain,
uncounted tab labels, so "is there anything waiting for me?" could only be
answered by opening all eight. This route answers it in one call.

Read-only and deliberately fan-out shaped: every count comes from the admin
BFF use case that already backs that queue's list route (tenant-scoped through
the same repositories), so the inbox can never disagree with the tab it labels.
Each probe is isolated: one unreadable queue is reported in ``unavailable``
(never as a silent ``0``) rather than failing the whole badge row.

Only queues that hold an admin decision are counted (owner decision,
2026-11-15). Absence notices and parent self-cancellations are history with no
action to take, so their tabs list them without a badge.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.inbox"])
log = logging.getLogger(__name__)

#: Queue ids, in the order the Inbox page renders its tabs. The frontend keys
#: its `?tab=` values off exactly these strings, so renaming one is a route
#: change, not a label change.
INBOX_QUEUE_IDS: tuple[str, ...] = (
    "registrations",
    "waitlist",
    "level-ups",
    "makeups",
    "trials",
    "absences",
    "cancellations",
    "pauses",
)

#: Informational tabs: listed on the Inbox page, never counted.
INFORMATIONAL_QUEUE_IDS: frozenset[str] = frozenset({"absences", "cancellations"})

#: The queues whose rows wait on an admin decision; these feed the badge.
DECISION_QUEUE_IDS: tuple[str, ...] = tuple(
    queue for queue in INBOX_QUEUE_IDS if queue not in INFORMATIONAL_QUEUE_IDS
)


class AdminInboxCountsView(BaseModel):
    """How many rows each decision queue is holding for a human right now.

    A queue whose count could not be read is absent from ``counts`` and named
    in ``unavailable`` so the page can say so instead of showing zero.
    """

    counts: dict[str, int]
    total: int
    unavailable: list[str] = []


@router.get("/inbox/counts", response_model=AdminInboxCountsView)
async def admin_inbox_counts(
    _claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminInboxCountsView:
    """Pending counts for every admin inbox queue, keyed by queue id."""

    probes: tuple[tuple[str, Callable[[], Awaitable[int]]], ...] = (
        ("registrations", lambda: _pending_registrations(use_cases)),
        ("waitlist", lambda: _waiting_seats(use_cases)),
        ("level-ups", lambda: _pending_level_ups(use_cases)),
        ("makeups", lambda: _pending_self_service(use_cases, "list_makeup_requests_for_admin")),
        ("trials", lambda: _pending_self_service(use_cases, "list_trial_requests_for_admin")),
        ("pauses", lambda: _pending_pauses(use_cases)),
    )
    values = await asyncio.gather(*(_safe_count(label, probe) for label, probe in probes))
    counts = {
        label: value for (label, _), value in zip(probes, values, strict=True) if value is not None
    }
    unavailable = [label for (label, _), value in zip(probes, values, strict=True) if value is None]
    return AdminInboxCountsView(counts=counts, total=sum(counts.values()), unavailable=unavailable)


async def _safe_count(label: str, probe: Callable[[], Awaitable[int]]) -> int | None:
    """One queue's count, or ``None`` with a warning when it cannot be read.

    The other queues still answer; the caller reports this one as unavailable.
    """
    try:
        return await probe()
    except Exception:
        log.warning("admin inbox queue count unavailable: %s", label, exc_info=True)
        return None


def _len(rows: Any) -> int:
    return len(list(rows))


async def _pending_registrations(use_cases: AdminUseCases) -> int:
    review = use_cases.admin_registration_review
    if review is None:
        return 0
    return _len(await review.list_pending())


async def _waiting_seats(use_cases: AdminUseCases) -> int:
    """Everyone queued for a seat on a class that has not ended.

    Summed from the session rows the sessions list already carries rather than
    re-reading each session's waitlist: the badge only needs the total, and the
    Waitlist tab itself still loads the per-session detail.
    """
    sessions = await use_cases.list_admin_sessions(None, window="open")  # type: ignore[operator]
    total = 0
    for session in sessions:
        raw = session if isinstance(session, dict) else session.model_dump()
        total += int(raw.get("waitlist_count") or 0)
    return total


async def _pending_level_ups(use_cases: AdminUseCases) -> int:
    progress = getattr(use_cases, "student_progress", None)
    if progress is None:
        return 0
    from backend.v2.contexts.student_progress.application.use_cases.get_level_up_queue import (
        GetLevelUpQueueCommand,
    )

    queue = await progress.get_level_up_queue.execute(GetLevelUpQueueCommand(program_id=None))
    return _len(queue)


async def _pending_self_service(use_cases: AdminUseCases, attribute: str) -> int:
    reader = getattr(use_cases, attribute, None)
    if reader is None:
        return 0
    return _len(await reader.execute("pending"))


async def _pending_pauses(use_cases: AdminUseCases) -> int:
    rows = await use_cases.list_admin_pause_requests.execute()
    return len([row for row in rows if getattr(row, "status", "") == "pending"])
