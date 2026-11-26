"""Admin dashboard aggregation routes."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from functools import partial
from typing import Any

from fastapi import APIRouter, Depends, Request

from backend.v2.contexts.enrollment.application.pricing_state import is_unpriced
from backend.v2.interfaces.admin.academy_clock import academy_today
from backend.v2.interfaces.admin.deps import AdminUseCases, get_admin_use_cases
from backend.v2.interfaces.admin.inbox_routes import missing_attendance_count
from backend.v2.interfaces.admin.views import (
    AdminAttentionItemView,
    AdminAttentionList,
    AdminAttentionUnavailableView,
)
from backend.v2.shared.auth.claims import AuthClaims
from backend.v2.shared.http import require_persona

router = APIRouter(tags=["admin.dashboard"])
log = logging.getLogger(__name__)

#: A parent pause request older than this has waited long enough that the
#: family is very likely being billed for a class they think they stopped
#: (issue #616): escalate the card rather than leaving it a flat count.
_STALE_PAUSE_REQUEST_DAYS = 7

#: How a failed source is named on the page ("Could not check <label>").
_SOURCE_LABELS: dict[str, str] = {
    "pending_registrations": "registrations",
    "dunning_alerts": "autopay failures",
    "overdue_dues": "overdue payments",
    "pause_requests": "pause requests",
    "stuck_scheduled_actions": "scheduled enrollment changes",
    "billing_deferral_warnings": "paused billing",
    "waivers": "waivers",
    "sessions": "today's classes",
    "missing_attendance": "missing attendance",
    "unpriced_classes": "unpriced classes",
}


def _oldest_pending_days(rows: list[Any]) -> int:
    """Age in whole days of the longest-waiting request (0 when none is datable).

    Measured instant-to-instant in UTC, never calendar-date-to-calendar-date:
    mixing a local ``date.today()`` with a UTC ``created_at`` is the #541/#608
    off-by-a-day family.
    """
    now = datetime.now(UTC)
    ages: list[int] = []
    for row in rows:
        created_at = getattr(row, "created_at", None)
        if not isinstance(created_at, datetime):
            continue
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        ages.append(max((now - created_at).days, 0))
    return max(ages, default=0)


@router.get("/dashboard/attention", response_model=AdminAttentionList)
async def dashboard_attention(
    request: Request,
    claims: AuthClaims = Depends(require_persona("admin")),
    use_cases: AdminUseCases = Depends(get_admin_use_cases),
) -> AdminAttentionList:
    """Aggregate dashboard attention signals from existing admin BFF sources.

    A source that fails is named in ``unavailable`` (owner rule: a count that
    fails to load is "unavailable", never a silent 0).
    """

    items: list[AdminAttentionItemView] = []
    unavailable: list[str] = []
    read = partial(_read_attention_source, unavailable)
    today = await academy_today(use_cases, claims.academy_id)

    # Issue #776: a registration waiting for a decision is the single most
    # time-sensitive thing an academy can be sitting on — the family has
    # usually already paid — and it used to appear nowhere on the home screen.
    pending_registrations = await read(
        "pending_registrations", _pending_registration_count, 0, use_cases
    )
    if pending_registrations:
        items.append(
            AdminAttentionItemView(
                attention_id="pending-registrations",
                kind="pending_registrations",
                title="Registrations waiting",
                detail=(
                    f"{pending_registrations} "
                    f"application{'s' if pending_registrations != 1 else ''} "
                    f"{'need' if pending_registrations != 1 else 'needs'} a decision."
                ),
                severity="high",
                href="/admin/inbox?tab=registrations",
                count=pending_registrations,
            )
        )

    # A class date that ended over 48h ago with nobody marked: the coach's own
    # "Recent, not fully marked" reminder has stopped showing it.
    missing_attendance = await read("missing_attendance", missing_attendance_count, 0, use_cases)
    if missing_attendance:
        items.append(
            AdminAttentionItemView(
                attention_id="missing-attendance",
                kind="missing_attendance",
                title="Attendance not taken",
                detail=(
                    f"{missing_attendance} class date{'s' if missing_attendance != 1 else ''} "
                    f"{'have' if missing_attendance != 1 else 'has'} no attendance marks."
                ),
                severity="medium",
                href="/admin/inbox?tab=attendance",
                count=missing_attendance,
            )
        )

    # Issue #774: the owner was never told when a card failed or when the
    # dunning ladder gave up — both only ever reached the parent. Optional on
    # the bundle so an older composition simply shows neither card.
    dunning_alerts = await read(
        "dunning_alerts",
        getattr(use_cases, "count_dunning_alerts", None) or _no_dunning_alerts,
        {},
    )
    failed_autopay = int(dunning_alerts.get("failed_autopay") or 0)
    if failed_autopay:
        items.append(
            AdminAttentionItemView(
                attention_id="autopay-failure",
                kind="autopay_failure",
                title="Autopay failures",
                detail=(
                    f"{failed_autopay} famil{'ies' if failed_autopay != 1 else 'y'} "
                    "had a card decline and are still on the retry ladder."
                ),
                severity="high",
                href="/admin/payments",
                count=failed_autopay,
            )
        )
    exhausted = int(dunning_alerts.get("dunning_exhausted") or 0)
    if exhausted:
        items.append(
            AdminAttentionItemView(
                attention_id="dunning-exhaustion",
                kind="dunning_exhaustion",
                title="Autopay switched off",
                detail=(
                    f"{exhausted} famil{'ies' if exhausted != 1 else 'y'} exhausted "
                    "every retry; autopay is off until the card is replaced."
                ),
                severity="high",
                href="/admin/payments",
                count=exhausted,
            )
        )

    stuck = int(dunning_alerts.get("autopay_stuck") or 0)
    needs_setup = int(dunning_alerts.get("autopay_needs_stripe_setup") or 0)
    if stuck or needs_setup:
        sentences = []
        if needs_setup:
            sentences.append(
                f"{needs_setup} famil{'ies' if needs_setup != 1 else 'y'} can't be charged "
                "until you finish Stripe setup."
            )
        if stuck:
            sentences.append(
                f"{stuck} famil{'ies' if stuck != 1 else 'y'} could not be charged because "
                "of a problem on our side, not the card."
            )
        # Billing health shows Stripe setup only; a fault on our side retries
        # on its own every run, so say that instead of pointing at a screen.
        sentences.append(
            "Nothing was charged. Open Billing health to finish setup."
            if needs_setup
            else "Nothing was charged; autopay tries again on its next run."
        )
        items.append(
            AdminAttentionItemView(
                attention_id="autopay-stuck",
                kind="autopay_stuck",
                title="Autopay stuck",
                detail=" ".join(sentences),
                severity="high",
                href="/admin/billing-health" if needs_setup else "/admin/payments",
                count=stuck + needs_setup,
            )
        )

    returns_to_review = int(dunning_alerts.get("bank_returns_to_review") or 0)
    if returns_to_review:
        items.append(
            AdminAttentionItemView(
                attention_id="bank-return-review",
                kind="bank_return_review",
                title="Bank returns to check",
                detail=(
                    f"{returns_to_review} "
                    f"{'family has' if returns_to_review == 1 else 'families have'} a bank "
                    "return that needs a manual look: the money came back, but the invoice "
                    "was not reopened automatically."
                ),
                severity="high",
                href="/admin/payments",
                count=returns_to_review,
            )
        )

    stuck_actions_reader = getattr(use_cases, "list_stuck_scheduled_actions", None)

    # Fan out all independent data fetches concurrently.
    stuck_actions: list[Any] = []

    if callable(stuck_actions_reader):
        (
            overdue_count,
            pause_requests,
            stuck_actions,
            billing_deferral_warnings,
            waiver_report,
            sessions,
        ) = await asyncio.gather(
            read("overdue_dues", _past_due_family_count, 0, request),
            read("pause_requests", use_cases.list_admin_pause_requests.execute, []),
            read("stuck_scheduled_actions", stuck_actions_reader, []),
            read(
                "billing_deferral_warnings",
                use_cases.list_billing_deferral_warnings,
                [],
                today=today,
                limit=100,
            ),
            read("waivers", use_cases.list_admin_waivers.execute, None),
            read("sessions", use_cases.list_admin_sessions, [], today),
        )
    else:
        (
            overdue_count,
            pause_requests,
            billing_deferral_warnings,
            waiver_report,
            sessions,
        ) = await asyncio.gather(
            read("overdue_dues", _past_due_family_count, 0, request),
            read("pause_requests", use_cases.list_admin_pause_requests.execute, []),
            read(
                "billing_deferral_warnings",
                use_cases.list_billing_deferral_warnings,
                [],
                today=today,
                limit=100,
            ),
            read("waivers", use_cases.list_admin_waivers.execute, None),
            read("sessions", use_cases.list_admin_sessions, [], today),
        )

    if overdue_count:
        items.append(
            AdminAttentionItemView(
                attention_id="overdue-dues",
                kind="overdue_dues",
                title="Overdue dues",
                detail=(
                    f"{overdue_count} famil{'ies' if overdue_count != 1 else 'y'} "
                    "past the due date without autopay cover, counting every month. "
                    "Payments lists the current month."
                ),
                severity="high",
                href="/admin/payments#bucket-past_due",
                count=overdue_count,
            )
        )

    pending_pauses = [row for row in pause_requests if getattr(row, "status", "") == "pending"]
    if pending_pauses:
        # Issue #616: a flat count let requests sit PENDING for months — the
        # parent believed they had paused while billing and dunning carried
        # on. The card now ages, so the queue gets louder the longer it waits.
        oldest_days = _oldest_pending_days(pending_pauses)
        stale = oldest_days >= _STALE_PAUSE_REQUEST_DAYS
        detail = (
            f"{len(pending_pauses)} request{'s' if len(pending_pauses) != 1 else ''} "
            "awaiting approval."
        )
        if stale:
            detail += f" Oldest waiting {oldest_days} day{'s' if oldest_days != 1 else ''}."
        items.append(
            AdminAttentionItemView(
                attention_id="pending-pause-requests",
                kind="pause_requests",
                title="Pending pause requests",
                detail=detail,
                severity="high" if stale else "medium",
                href="/admin/inbox?tab=pauses",
                count=len(pending_pauses),
            )
        )

    # Issue #675 follow-up: one reader, two very different problems — a resume
    # that could not find a seat, and a month-end cancel that gave up after its
    # retries. They get their own items so an admin is not told a lost
    # cancellation is a capacity problem.
    blocked_resumes = [
        row for row in stuck_actions if str(_field(row, "status", "")) == "blocked_capacity"
    ]
    failed_actions = [row for row in stuck_actions if str(_field(row, "status", "")) == "failed"]

    if blocked_resumes:
        count = len(blocked_resumes)
        items.append(
            AdminAttentionItemView(
                attention_id="scheduled-resume-blocked",
                kind="scheduled_resume_blocked",
                title="Scheduled resume blocked",
                detail=(
                    f"{count} enrollment{'s' if count != 1 else ''} could not resume "
                    "because the class is full."
                ),
                severity="medium",
                href="/admin/inbox?tab=pauses",
                count=count,
            )
        )

    if failed_actions:
        count = len(failed_actions)
        items.append(
            AdminAttentionItemView(
                attention_id="scheduled-action-failed",
                kind="scheduled_action_failed",
                title="Scheduled enrollment change failed",
                detail=(
                    f"{count} scheduled change{'s' if count != 1 else ''} "
                    "(such as an end-of-period cancellation) could not be applied "
                    "and needs a manual fix."
                ),
                severity="high",
                href="/admin/inbox?tab=cancellations",
                count=count,
            )
        )

    if billing_deferral_warnings:
        count = len(billing_deferral_warnings)
        high_count = len(
            [
                row
                for row in billing_deferral_warnings
                if str(_field(row, "severity", "medium")) == "high"
            ]
        )
        items.append(
            AdminAttentionItemView(
                attention_id="billing-deferral-risks",
                kind="billing_deferrals",
                title="Paused billing needs review",
                detail=(
                    f"{count} enrollment{'s' if count != 1 else ''} have paused billing "
                    "risk or legacy skip metadata."
                ),
                severity="high" if high_count else "medium",
                href="/admin/payments",
                count=count,
            )
        )

    waiver_count = (
        waiver_report.summary.pending_count + waiver_report.summary.outdated_count
        if waiver_report is not None
        else 0
    )
    if waiver_count:
        items.append(
            AdminAttentionItemView(
                attention_id="waiver-status",
                kind="waivers",
                title="Waivers need review",
                # Name the next step: families sign the current version from
                # their own Waivers page; the admin sees who is still due here.
                detail=(
                    f"{waiver_report.summary.pending_count} pending, "
                    f"{waiver_report.summary.outdated_count} outdated. Families sign "
                    "the current version from their Waivers page; open Family "
                    "policies to see who is still due."
                ),
                severity="medium",
                href="/admin/settings?panel=family-policies",
                count=waiver_count,
            )
        )

    # S10: a class with children in it and no fee bills nothing, silently.
    # A free class (fee 0) is a choice and is not listed.
    unpriced = await read("unpriced_classes", _unpriced_classes_with_students, [], use_cases)
    if unpriced:
        names = ", ".join(
            f"{_field(s, 'title', 'Class')} ({int(_field(s, 'enrolled_count', 0) or 0)} "
            f"student{'s' if int(_field(s, 'enrolled_count', 0) or 0) != 1 else ''})"
            for s in unpriced[:3]
        )
        more = f" and {len(unpriced) - 3} more" if len(unpriced) > 3 else ""
        items.append(
            AdminAttentionItemView(
                attention_id="unpriced-classes",
                kind="unpriced_classes",
                title="Classes with students and no price",
                detail=f"{names}{more}. The owner must set a price before these can be billed.",
                severity="high",
                href=(
                    f"/admin/sessions/{_field(unpriced[0], 'session_id')}"
                    if len(unpriced) == 1
                    else "/admin/sessions"
                ),
                count=len(unpriced),
            )
        )

    pressured = [p for p in (_session_pressure(s) for s in sessions) if p is not None]
    if pressured:
        items.append(
            AdminAttentionItemView(
                attention_id="session-pressure",
                kind="session_pressure",
                title="Session pressure",
                detail=f"{len(pressured)} session{'s' if len(pressured) != 1 else ''} full or waitlisted today.",
                severity="low",
                href="/admin/sessions",
                count=len(pressured),
            )
        )

    return AdminAttentionList(
        items=items,
        unavailable=[
            AdminAttentionUnavailableView(source=label, label=_SOURCE_LABELS.get(label, label))
            for label in unavailable
        ],
    )


async def _unpriced_classes_with_students(use_cases: AdminUseCases) -> list[Any]:
    """Live (not ended) classes with at least one seat taken and no fee set."""
    rows = await use_cases.list_admin_sessions(None, window="open", coach_id=None)  # type: ignore[operator]
    return [
        row
        for row in rows
        if _field(row, "status") != "cancelled"
        and int(_field(row, "enrolled_count", 0) or 0) > 0
        and is_unpriced(_field(row, "amount_cents"))
    ]


async def _pending_registration_count(use_cases: AdminUseCases) -> int:
    review = use_cases.admin_registration_review
    if review is None:
        return 0
    return len(list(await review.list_pending()))


async def _no_dunning_alerts() -> dict[str, int]:
    """Fallback when the bundle predates the autopay attention sources (#774)."""
    return {}


async def _past_due_family_count(request: Request) -> int:
    """Families past the due date without autopay cover, in ANY period (L2 B2).

    Overdue means the day after the due date on the academy's clock; drafts
    never count. A missing reader raises, so the card reads "unavailable".
    """
    counts = await request.app.state.admin_overdue_families.counts()
    return int(counts["past_due"])


async def _read_attention_source(
    unavailable: list[str],
    label: str,
    reader: Callable[..., Awaitable[Any]],
    default: Any,
    *args: Any,
    **kwargs: Any,
) -> Any:
    try:
        return await reader(*args, **kwargs)
    except Exception:
        log.warning("admin dashboard attention source unavailable: %s", label, exc_info=True)
        unavailable.append(label)
        return default


def _field(session: Any, name: str, default: Any = None) -> Any:
    if isinstance(session, dict):
        return session.get(name, default)
    return getattr(session, name, default)


def _session_pressure(session: Any) -> str | None:
    enrolled = int(_field(session, "enrolled_count", 0) or 0)
    waitlist = int(_field(session, "waitlist_count", 0) or 0)
    capacity = int(_field(session, "capacity", 0) or 0)
    if waitlist > 0:
        return "waitlisted"
    if capacity > 0 and enrolled >= capacity:
        return "full"
    return None
