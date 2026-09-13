"""Owner daily brief (issue #776).

The only daily email this deployment sent was ``ops_digest`` — quarantined
webhooks, dead-letter events, stale jobs — written for whoever keeps the
servers up. The person who runs the academy had no daily email at all, so the
things that only a human can resolve (an application waiting for a decision, a
family whose card failed, a student with no waiver, an address that has stopped
accepting mail) were only visible to someone who went looking.

This is that second email. It deliberately does NOT replace the ops digest:
the audiences and the content share nothing, and the channel that reports
"email is broken" must keep its own recipient. ``main.py`` owns the cron job,
the lease and the send port, exactly as it does for the ops digest.

Read-only, cross-tenant and collection-name-driven for the same reason
``ops_digest`` is: the brief spans onboarding, enrollment, billing and
communications at once, so binding it to any one context's repositories would
drag a bounded context into ``shared/``. Registered as a documented cross-
tenant exception in ``v2/tests/test_no_raw_tenant_mongo_access.py``.

Every probe is isolated: one unreadable collection becomes a line under
"could not be read" rather than losing the whole brief. A partially readable
database is exactly when the owner most needs the email.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from html import escape
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

log = logging.getLogger(__name__)

OWNER_BRIEF_JOB = "send_owner_daily_brief"

LOOKBACK = timedelta(hours=24)

#: Lifecycle events that mean a student stopped attending. Mirrors the
#: ``EnrollmentLifecycleEventType`` terminals; ``shared/`` may not import the
#: enrollment context, so the list is duplicated here and pinned by
#: ``test_owner_daily_brief.py::test_departure_events_match_the_domain``.
DEPARTURE_EVENT_TYPES: tuple[str, ...] = (
    "cancelled",
    "withdrawn",
    "dropped",
    "removed",
)

#: An invoice with money still owed on it. ``draft`` is not yet the family's
#: problem and ``void`` never was.
OPEN_INVOICE_STATUSES: tuple[str, ...] = ("open", "partially_paid")


@dataclass(frozen=True)
class DepartureReason:
    reason: str
    count: int


@dataclass(frozen=True)
class OwnerDailyBrief:
    generated_at: datetime
    lookback_hours: int
    new_enrollments: int = 0
    departures: tuple[DepartureReason, ...] = ()
    approvals_waiting: int = 0
    payments_failed: int = 0
    invoices_open: int = 0
    waivers_missing: int = 0
    emails_undeliverable: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def departures_total(self) -> int:
        return sum(row.count for row in self.departures)

    @property
    def has_attention_items(self) -> bool:
        """Does anything here need a person today?

        ``new_enrollments`` is deliberately excluded: good news is worth
        reporting but must never be what makes the subject line say the owner
        has work waiting, or the flag stops meaning anything.
        """
        return bool(
            self.approvals_waiting
            or self.payments_failed
            or self.waivers_missing
            or self.emails_undeliverable
            or self.departures
        )


async def collect_owner_daily_brief(
    db: AsyncIOMotorDatabase[Any],
    *,
    now: datetime | None = None,
    lookback: timedelta = LOOKBACK,
) -> OwnerDailyBrief:
    generated_at = now or datetime.now(UTC)
    since = generated_at - lookback

    probes: list[tuple[str, Any]] = [
        ("new_enrollments", _new_enrollments(db, since)),
        ("departures", _departures(db, since)),
        ("approvals_waiting", _approvals_waiting(db)),
        ("money", _money(db, since)),
        ("waivers_missing", _waivers_missing(db)),
        ("emails_undeliverable", _emails_undeliverable(db, since)),
    ]
    results = await asyncio.gather(*(coro for _, coro in probes), return_exceptions=True)

    values: dict[str, Any] = {}
    errors: list[str] = []
    for (label, _), result in zip(probes, results, strict=True):
        if isinstance(result, BaseException):
            errors.append(f"{label}: {result}")
            continue
        values.update(result)

    return OwnerDailyBrief(
        generated_at=generated_at,
        lookback_hours=int(lookback.total_seconds() // 3600),
        errors=errors,
        **values,
    )


async def _new_enrollments(db: AsyncIOMotorDatabase[Any], since: datetime) -> dict[str, Any]:
    count = await db["enrollments"].count_documents({"enrolled_at": {"$gte": since}})
    return {"new_enrollments": int(count)}


async def _departures(db: AsyncIOMotorDatabase[Any], since: datetime) -> dict[str, Any]:
    """Who left in the window, grouped by the reason recorded at the time.

    The reason is the point of this line: "3 students left" starts a search,
    "3 students left — 2 moved away, 1 cost" starts a decision.
    """
    cursor = db["enrollment_events"].aggregate(
        [
            {
                "$match": {
                    "event_type": {"$in": list(DEPARTURE_EVENT_TYPES)},
                    "occurred_at": {"$gte": since},
                }
            },
            {"$group": {"_id": "$reason", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]
    )
    rows: list[DepartureReason] = []
    async for row in cursor:
        rows.append(
            DepartureReason(
                reason=str(row.get("_id") or "no reason recorded"),
                count=int(row.get("count") or 0),
            )
        )
    return {"departures": tuple(rows)}


async def _approvals_waiting(db: AsyncIOMotorDatabase[Any]) -> dict[str, Any]:
    # Not windowed: an application that has waited three days is more urgent
    # than one that arrived this morning, not less.
    count = await db["onboarding_applications"].count_documents({"status": "PENDING_APPROVAL"})
    return {"approvals_waiting": int(count)}


async def _money(db: AsyncIOMotorDatabase[Any], since: datetime) -> dict[str, Any]:
    failed = await db["payments"].count_documents(
        {"status": "failed", "updated_at": {"$gte": since}}
    )
    open_invoices = await db["invoices"].count_documents(
        {"status": {"$in": list(OPEN_INVOICE_STATUSES)}, "balance_due_cents": {"$gt": 0}}
    )
    return {"payments_failed": int(failed), "invoices_open": int(open_invoices)}


async def _waivers_missing(db: AsyncIOMotorDatabase[Any]) -> dict[str, Any]:
    """Students with no waiver acceptance on file at all.

    Set difference rather than a join: both collections are small, and a
    ``$lookup`` here would need an index this once-a-day query is the only
    caller of. Outdated-version waivers are the admin waivers page's job; this
    line is the one that carries legal risk.
    """
    students = {
        str(doc.get("student_id") or doc.get("_id"))
        async for doc in db["students"].find({}, {"student_id": 1})
    }
    signed = {
        str(doc.get("student_id"))
        async for doc in db["waiver_acceptances"].find({}, {"student_id": 1})
    }
    return {"waivers_missing": len(students - signed - {"None", ""})}


async def _emails_undeliverable(db: AsyncIOMotorDatabase[Any], since: datetime) -> dict[str, Any]:
    """Addresses that started bouncing in the window and are still suppressed.

    These are families the academy can no longer reach at all — every later
    invoice, digest and class notice to them is silently dropped by the #556
    gate until someone collects a new address.
    """
    count = await db["email_suppressions"].count_documents(
        {"active": True, "first_seen_at": {"$gte": since}}
    )
    return {"emails_undeliverable": int(count)}


def render_owner_daily_brief(brief: OwnerDailyBrief) -> tuple[str, str]:
    """``(subject, html_body)``.

    The date label is taken from ``generated_at`` verbatim, so the caller must
    pass a ``now`` in the scheduler timezone — a UTC stamp would put
    yesterday's date on a 07:00 email in any UTC+ deployment.
    """
    date_label = brief.generated_at.strftime("%Y-%m-%d")
    subject = (
        f"Academy brief {date_label} — action needed"
        if brief.has_attention_items
        else f"Academy brief {date_label} — nothing waiting"
    )

    window = f"last {brief.lookback_hours}h"
    rows = [
        ("New enrollments", brief.new_enrollments, window, False),
        ("Students who left", brief.departures_total, window, True),
        ("Registrations waiting for a decision", brief.approvals_waiting, "all open", True),
        ("Payments that failed", brief.payments_failed, window, True),
        ("Invoices still owing", brief.invoices_open, "all open", False),
        ("Students with no waiver", brief.waivers_missing, "all time", True),
        ("Families we can no longer email", brief.emails_undeliverable, window, True),
    ]
    row_html = "".join(
        f"<tr><td>{escape(label)}</td><td align='right'>"
        f"{f'<strong>{count}</strong>' if actionable and count else count}</td>"
        f"<td>{escape(note)}</td></tr>"
        for label, count, note, actionable in rows
    )

    parts = [
        f"<h2>Academy brief — {escape(date_label)}</h2>",
        "<table cellpadding='6' cellspacing='0' border='0'>",
        "<tr><th align='left'>Signal</th><th align='right'>Count</th>",
        "<th align='left'>Window</th></tr>",
        row_html,
        "</table>",
        _render_departures(brief),
    ]
    if brief.errors:
        items = "".join(f"<li>{escape(item)}</li>" for item in brief.errors)
        parts.append(f"<h3>Could not be read</h3><ul>{items}</ul>")
    if not brief.has_attention_items:
        parts.append("<p>Nothing is waiting on a decision today.</p>")
    return subject, "".join(parts)


def _render_departures(brief: OwnerDailyBrief) -> str:
    if not brief.departures:
        return ""
    items = "".join(f"<li>{escape(row.reason)} — {row.count}</li>" for row in brief.departures)
    return f"<h3>Why students left</h3><ul>{items}</ul>"
