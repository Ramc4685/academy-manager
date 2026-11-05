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
the lease and the send port; ``composition/owner_brief.py`` loops the
academies and decides who receives each one.

One brief per academy. Every probe filters by the ``academy_id`` it is given,
so an owner only ever sees their own academy's numbers (the first version
summed every tenant into one email). Read-only and collection-name-driven:
the brief spans onboarding, enrollment, billing and communications at once,
so binding it to any one context's repositories would drag a bounded context
into ``shared/`` (which may not import ``contexts/``).

Every probe is isolated: one unreadable collection becomes a line under
"could not be read" rather than losing the whole brief. A partially readable
database is exactly when the owner most needs the email.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
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

#: ``source_key`` prefix of the job-created "trial passed, no registration"
#: follow-up (``crm/domain/family_notes.py``; duplicated, ``shared/`` may not
#: import ``contexts/``), pinned by ``test_trial_passed_prefix_matches_the_domain``.
TRIAL_PASSED_SOURCE_PREFIX = "trial_passed:"

#: ``payment_attempts`` statuses that mean a charge was tried and did not take
#: money (``billing/application/family_billing.FAILURE_ATTEMPT_STATUSES``;
#: duplicated, ``shared/`` may not import ``contexts/``), pinned by
#: ``test_failed_attempt_statuses_match_billing``. A declined autopay lands
#: here, not on the legacy ``payments`` collection.
FAILED_ATTEMPT_STATUSES: tuple[str, ...] = (
    "failed",
    "declined",
    "requires_action",
    "error",
    "canceled",
    "cancelled",
)

#: The "three things today" lines, in the order they are rendered.
THREE_THINGS_LABELS: tuple[str, str, str] = (
    "Failed cards",
    "Trial passed, not registered",
    "At-risk families",
)
#: How many family names each line carries.
THREE_THINGS_NAMES = 5


@dataclass(frozen=True)
class BriefFamily:
    family_id: str
    name: str


@dataclass(frozen=True)
class FamilyFacts:
    """What the three-things lines need from the People CRM family index.

    Handed in by ``composition/owner_brief.py`` (``family_facts_source``):
    a child's at_risk state is the enrollment context's derivation and the
    family's name and aliases are the CRM's, neither of which ``shared/``
    may import.
    """

    #: Any stored parent reference -> canonical family id.
    family_by_alias: Mapping[str, str]
    name_by_family: Mapping[str, str]
    #: Families with at least one child whose lifecycle is ``at_risk``.
    at_risk: tuple[BriefFamily, ...]

    def family(self, parent_ref: str) -> BriefFamily:
        family_id = self.family_by_alias.get(parent_ref, parent_ref)
        return BriefFamily(
            family_id=family_id, name=self.name_by_family.get(family_id) or family_id
        )


FamilyFactsSource = Callable[[str], Awaitable[FamilyFacts]]


@dataclass(frozen=True)
class ThingRow:
    label: str
    #: ``None`` when the probe failed: the line says "could not be read".
    count: int | None
    #: At most :data:`THREE_THINGS_NAMES` distinct families, first seen first.
    families: tuple[BriefFamily, ...] = ()


def _unread_things() -> tuple[ThingRow, ThingRow, ThingRow]:
    a, b, c = (ThingRow(label=label, count=None) for label in THREE_THINGS_LABELS)
    return (a, b, c)


@dataclass(frozen=True)
class DepartureReason:
    reason: str
    count: int


@dataclass(frozen=True)
class OwnerDailyBrief:
    generated_at: datetime
    lookback_hours: int
    academy_id: str = ""
    #: Display name from the ``academies`` registry, falling back to the id.
    academy_name: str = ""
    new_enrollments: int = 0
    departures: tuple[DepartureReason, ...] = ()
    approvals_waiting: int = 0
    payments_failed: int = 0
    invoices_open: int = 0
    waivers_missing: int = 0
    emails_undeliverable: int = 0
    #: Failed cards, trial passed but not registered, at-risk families.
    three_things: tuple[ThingRow, ThingRow, ThingRow] = field(default_factory=_unread_things)
    #: Base URL of the academy's admin app for family links; empty = no links.
    base_url: str = ""
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
        failed_cards, trial_passed, at_risk = self.three_things
        return bool(
            self.approvals_waiting
            or self.payments_failed
            or self.waivers_missing
            or self.emails_undeliverable
            or self.departures
            or failed_cards.count
            or trial_passed.count
            or at_risk.count
        )


async def collect_owner_daily_brief(
    db: AsyncIOMotorDatabase[Any],
    *,
    academy_id: str,
    family_facts: FamilyFactsSource,
    now: datetime | None = None,
    lookback: timedelta = LOOKBACK,
    base_url: str = "",
) -> OwnerDailyBrief:
    if not academy_id:
        raise ValueError("collect_owner_daily_brief requires an academy_id")
    generated_at = now or datetime.now(UTC)
    since = generated_at - lookback

    errors: list[str] = []
    try:
        facts: FamilyFacts | None = await family_facts(academy_id)
    except Exception as exc:  # names degrade to ids; only the at-risk line is lost
        errors.append(f"families: {exc}")
        facts = None

    probes: list[tuple[str, Any]] = [
        ("new_enrollments", _new_enrollments(db, academy_id, since)),
        ("departures", _departures(db, academy_id, since)),
        ("approvals_waiting", _approvals_waiting(db, academy_id)),
        ("money", _money(db, academy_id, since)),
        ("waivers_missing", _waivers_missing(db, academy_id)),
        ("emails_undeliverable", _emails_undeliverable(db, academy_id, since)),
        ("failed_cards", _failed_cards(db, academy_id, since, facts)),
        ("trial_passed", _trial_passed(db, academy_id, facts)),
        ("at_risk", _at_risk(facts)),
    ]
    results = await asyncio.gather(*(coro for _, coro in probes), return_exceptions=True)

    values: dict[str, Any] = {}
    for (label, _), result in zip(probes, results, strict=True):
        if isinstance(result, BaseException):
            errors.append(f"{label}: {result}")
            continue
        values.update(result)

    unread = _unread_things()
    three_things = (
        values.pop("failed_cards", unread[0]),
        values.pop("trial_passed", unread[1]),
        values.pop("at_risk", unread[2]),
    )
    return OwnerDailyBrief(
        generated_at=generated_at,
        lookback_hours=int(lookback.total_seconds() // 3600),
        academy_id=academy_id,
        academy_name=await _academy_name(db, academy_id),
        three_things=three_things,
        base_url=base_url.rstrip("/"),
        errors=errors,
        **values,
    )


async def _academy_name(db: AsyncIOMotorDatabase[Any], academy_id: str) -> str:
    """The academy's display name; the id when the registry cannot say.

    Never raises: a missing name must not cost the owner their brief.
    """
    try:
        doc = await db["academies"].find_one(
            {"academy_id": academy_id}, {"display_name": 1, "name": 1}
        )
    except Exception:  # degrade to the id, like every probe
        log.warning("owner_brief_academy_name_unreadable academy_id=%s", academy_id)
        return academy_id
    name = (doc or {}).get("display_name") or (doc or {}).get("name")
    return str(name) if name else academy_id


async def _new_enrollments(
    db: AsyncIOMotorDatabase[Any], academy_id: str, since: datetime
) -> dict[str, Any]:
    count = await db["enrollments"].count_documents(
        {"academy_id": academy_id, "enrolled_at": {"$gte": since}}
    )
    return {"new_enrollments": int(count)}


async def _departures(
    db: AsyncIOMotorDatabase[Any], academy_id: str, since: datetime
) -> dict[str, Any]:
    """Who left in the window, grouped by the reason recorded at the time.

    The reason is the point of this line: "3 students left" starts a search,
    "3 students left — 2 moved away, 1 cost" starts a decision.
    """
    cursor = db["enrollment_events"].aggregate(
        [
            {
                "$match": {
                    "academy_id": academy_id,
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


async def _approvals_waiting(db: AsyncIOMotorDatabase[Any], academy_id: str) -> dict[str, Any]:
    # Not windowed: an application that has waited three days is more urgent
    # than one that arrived this morning, not less.
    count = await db["onboarding_applications"].count_documents(
        {"academy_id": academy_id, "status": "PENDING_APPROVAL"}
    )
    return {"approvals_waiting": int(count)}


async def _money(db: AsyncIOMotorDatabase[Any], academy_id: str, since: datetime) -> dict[str, Any]:
    failed = await db["payments"].count_documents(
        {"academy_id": academy_id, "status": "failed", "updated_at": {"$gte": since}}
    )
    open_invoices = await db["invoices"].count_documents(
        {
            "academy_id": academy_id,
            "status": {"$in": list(OPEN_INVOICE_STATUSES)},
            "balance_due_cents": {"$gt": 0},
        }
    )
    return {"payments_failed": int(failed), "invoices_open": int(open_invoices)}


def _named(
    parent_refs: list[str], facts: FamilyFacts | None, *, count: int, label: str
) -> ThingRow:
    """One three-things line: ``count`` plus the first distinct families."""
    families: list[BriefFamily] = []
    for ref in parent_refs:
        family = facts.family(ref) if facts is not None else BriefFamily(ref, ref)
        if family not in families:
            families.append(family)
        if len(families) == THREE_THINGS_NAMES:
            break
    return ThingRow(label=label, count=count, families=tuple(families))


async def _failed_cards(
    db: AsyncIOMotorDatabase[Any], academy_id: str, since: datetime, facts: FamilyFacts | None
) -> dict[str, Any]:
    """Charge attempts in the window that did not take money, with who they belong to.

    Same source and filters as the family-money read model's "last failure":
    autopay declines are recorded on ``payment_attempts``, so the legacy
    ``payments`` counter (``payments_failed``) misses them.
    """
    refs: list[str] = []
    async for doc in db["payment_attempts"].find(
        {
            "academy_id": academy_id,
            "status": {"$in": list(FAILED_ATTEMPT_STATUSES)},
            "created_at": {"$gte": since},
        },
        {"parent_id": 1},
    ):
        refs.append(str(doc.get("parent_id") or ""))
    row = _named([r for r in refs if r], facts, count=len(refs), label=THREE_THINGS_LABELS[0])
    return {"failed_cards": row}


async def _trial_passed(
    db: AsyncIOMotorDatabase[Any], academy_id: str, facts: FamilyFacts | None
) -> dict[str, Any]:
    """Open job-created "trial passed, no registration" follow-ups."""
    refs: list[str] = []
    async for doc in db["family_follow_ups"].find(
        {"academy_id": academy_id, "status": "open"}, {"parent_id": 1, "source_key": 1}
    ):
        # Prefix filtered here: open follow-ups are few and a $regex would
        # need its own index for this once-a-day read.
        if str(doc.get("source_key") or "").startswith(TRIAL_PASSED_SOURCE_PREFIX):
            refs.append(str(doc.get("parent_id") or ""))
    row = _named(refs, facts, count=len(refs), label=THREE_THINGS_LABELS[1])
    return {"trial_passed": row}


async def _at_risk(facts: FamilyFacts | None) -> dict[str, Any]:
    if facts is None:
        raise RuntimeError("family index unavailable")
    row = ThingRow(
        label=THREE_THINGS_LABELS[2],
        count=len(facts.at_risk),
        families=facts.at_risk[:THREE_THINGS_NAMES],
    )
    return {"at_risk": row}


async def _waivers_missing(db: AsyncIOMotorDatabase[Any], academy_id: str) -> dict[str, Any]:
    """This academy's students with no waiver acceptance on file at all.

    Set difference rather than a join: both collections are small, and a
    ``$lookup`` here would need an index this once-a-day query is the only
    caller of. Outdated-version waivers are the admin waivers page's job; this
    line is the one that carries legal risk.

    Acceptances are matched the way the admin waivers page matches them
    (``MongoAdminWaiverRepository``): this academy's rows OR pre-tenancy rows
    with no ``academy_id``, restricted to this academy's own student ids — so
    a legacy acceptance still counts for its student and never for anyone
    else's.
    """
    students = {
        str(doc.get("student_id") or doc.get("_id"))
        async for doc in db["students"].find({"academy_id": academy_id}, {"student_id": 1})
    } - {"None", ""}
    if not students:
        return {"waivers_missing": 0}
    signed = {
        str(doc.get("student_id"))
        async for doc in db["waiver_acceptances"].find(
            {
                "student_id": {"$in": sorted(students)},
                "$or": [
                    {"academy_id": academy_id},
                    {"academy_id": {"$exists": False}},
                    {"academy_id": None},
                ],
            },
            {"student_id": 1},
        )
    }
    return {"waivers_missing": len(students - signed)}


async def _family_emails(db: AsyncIOMotorDatabase[Any], academy_id: str) -> set[str]:
    """Lower-cased addresses of this academy's families.

    "The academy's families" is the definition the session audience resolver
    uses (``MongoAudienceResolver.resolve_session_audience`` and
    ``_with_family_contacts``): the parent ids on this academy's students,
    resolved against this academy's user docs or legacy global ones (by
    ``user_id`` or the ``auth_uid`` alias), plus this academy's
    ``family_contacts`` rows.
    """
    parent_ids: set[str] = set()
    async for doc in db["students"].find(
        {"academy_id": academy_id}, {"parent_id": 1, "parent_user_id": 1}
    ):
        pid = doc.get("parent_id") or doc.get("parent_user_id")
        if pid:
            parent_ids.add(str(pid))

    emails: set[str] = set()
    if parent_ids:
        ids = sorted(parent_ids)
        async for doc in db["users"].find(
            {
                "academy_id": {"$in": [academy_id, None]},
                "$or": [{"user_id": {"$in": ids}}, {"auth_uid": {"$in": ids}}],
            },
            {"email": 1},
        ):
            if doc.get("email"):
                emails.add(str(doc["email"]).strip().lower())
    async for doc in db["family_contacts"].find({"academy_id": academy_id}, {"email": 1}):
        if doc.get("email"):
            emails.add(str(doc["email"]).strip().lower())
    emails.discard("")
    return emails


async def _emails_undeliverable(
    db: AsyncIOMotorDatabase[Any], academy_id: str, since: datetime
) -> dict[str, Any]:
    """This academy's family addresses that started bouncing in the window
    and are still suppressed.

    These are families the academy can no longer reach at all — every later
    invoice, digest and class notice to them is silently dropped by the #556
    gate until someone collects a new address.

    ``email_suppressions`` is deliberately global, keyed by address (the
    Resend sender domain is shared, so a bounce seen by one academy must stop
    every academy mailing that address — see ``MongoSuppressionRepository``).
    Its ``first_seen_academy_id`` is best-effort audit attribution and must
    not be used as a filter. So the suppression list is intersected with this
    academy's own family addresses instead: an address shared by two
    academies' families is (correctly) reported to both owners, and a
    stranger's bounce is reported to nobody.
    """
    emails = await _family_emails(db, academy_id)
    if not emails:
        return {"emails_undeliverable": 0}
    count = await db["email_suppressions"].count_documents(
        {"email": {"$in": sorted(emails)}, "active": True, "first_seen_at": {"$gte": since}}
    )
    return {"emails_undeliverable": int(count)}


def render_owner_daily_brief(brief: OwnerDailyBrief) -> tuple[str, str]:
    """``(subject, html_body)``.

    The date label is taken from ``generated_at`` verbatim, so the caller must
    pass a ``now`` in the scheduler timezone — a UTC stamp would put
    yesterday's date on a 07:00 email in any UTC+ deployment.
    """
    date_label = brief.generated_at.strftime("%Y-%m-%d")
    # The "Academy brief <date> — ..." prefix is what existing inbox filters
    # match on, so the academy name goes at the end.
    subject = (
        f"Academy brief {date_label} — action needed"
        if brief.has_attention_items
        else f"Academy brief {date_label} — nothing waiting"
    )
    academy_label = brief.academy_name or brief.academy_id
    if academy_label:
        subject = f"{subject} · {academy_label}"

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
        (
            f"<h2>{escape(academy_label)} — academy brief {escape(date_label)}</h2>"
            if academy_label
            else f"<h2>Academy brief — {escape(date_label)}</h2>"
        ),
        _render_three_things(brief),
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


def _render_three_things(brief: OwnerDailyBrief) -> str:
    """Always all three lines, in order; a failed probe says so on its line."""
    items = []
    for row in brief.three_things:
        if row.count is None:
            detail = "could not be read"
        elif not row.count:
            detail = "none"
        else:
            names = ", ".join(_family_link(brief.base_url, f) for f in row.families)
            detail = f"{row.count}: {names}" if names else str(row.count)
        items.append(f"<li><strong>{escape(row.label)}</strong> — {detail}</li>")
    return f"<h3>Three things today</h3><ol>{''.join(items)}</ol>"


def _family_link(base_url: str, family: BriefFamily) -> str:
    name = escape(family.name)
    if not base_url:
        return name
    href = escape(f"{base_url}/admin/families/{family.family_id}", quote=True)
    return f"<a href='{href}'>{name}</a>"


def _render_departures(brief: OwnerDailyBrief) -> str:
    if not brief.departures:
        return ""
    items = "".join(f"<li>{escape(row.reason)} — {row.count}</li>" for row in brief.departures)
    return f"<h3>Why students left</h3><ul>{items}</ul>"
