"""The unified family timeline: entry shape, merge, dedupe, paging, money redaction.

People CRM engineering spec §5 "Timeline" (Phase 5, roadmap L4a/L4b). Pure
functions only: no Mongo, no clock. Each source (billing's family timeline,
attendance, requests, the admin audit allowlist, coach notes, CRM records)
turns its own rows into :class:`TimelineEntry` values; this module merges
them into one newest-first feed.

Rules kept here:

* **Times are aware UTC** (:func:`as_utc`). A naive Mongo datetime is read as
  UTC, never compared against an aware one (#706).
* **Order** is ``at`` descending, then ``entry_id`` ascending, so two pages
  never disagree about which of two same-second entries comes first.
* **Dedupe**: one approved pause writes a request decision, an enrollment
  event and an autopay change. Non-money entries that share an
  ``enrollment_id`` and fall inside :data:`DEDUPE_WINDOW` of the cluster's
  first entry collapse into one; the kept entry lists the others in
  ``collapsed_codes``. Money entries never collapse: an amount is never hidden
  behind another row.
* **Cap**: the merged feed is cut to :data:`TIMELINE_CAP` before paging.
* **Money redaction** (#553): a caller who may not see amounts (front desk)
  gets every money entry with ``amount_cents`` / ``refunded_cents`` removed
  and every summary segment that carries a dollar figure dropped.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Literal

TimelineKind = Literal[
    "money",
    "lifecycle",
    "attendance",
    "requests",
    "comms",
    "coach",
    "admin",
    "crm",
]

TIMELINE_KINDS: tuple[TimelineKind, ...] = (
    "money",
    "lifecycle",
    "attendance",
    "requests",
    "comms",
    "coach",
    "admin",
    "crm",
)

#: Spec §5: each source is read newest-first with this limit, and the merged
#: feed is cut to it.
TIMELINE_CAP = 200
SOURCE_LIMIT = 200
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

#: Spec §5 "Dedupe": entries of one enrollment inside this window are one event.
DEDUPE_WINDOW = timedelta(minutes=10)

#: Which entry of a collapsed cluster is kept: the most telling one.
_KEEP_PRIORITY: dict[str, int] = {
    "lifecycle": 0,
    "requests": 1,
    "admin": 2,
    "attendance": 3,
    "crm": 4,
    "coach": 5,
    "comms": 6,
}


@dataclass(frozen=True)
class TimelineEntry:
    #: Stable per source row (``"<source>:<row id>[:<event>]"``); the paging
    #: tiebreak and the React key.
    entry_id: str
    at: datetime
    kind: TimelineKind
    code: str
    summary: str
    source: str
    #: Optional longer text shown under the summary (a note or coach note body).
    detail: str | None = None
    student_id: str | None = None
    student_name: str | None = None
    enrollment_id: str | None = None
    invoice_id: str | None = None
    invoice_ids: tuple[str, ...] = ()
    actor_id: str | None = None
    actor_name: str | None = None
    reason: str | None = None
    amount_cents: int | None = None
    refunded_cents: int | None = None
    muted: bool = False
    collapsed_codes: tuple[str, ...] = ()


def as_utc(value: datetime) -> datetime:
    """Aware UTC; a naive value is taken to be UTC (Mongo returns naive)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _sort_key(entry: TimelineEntry) -> tuple[float, str]:
    return (-as_utc(entry.at).timestamp(), entry.entry_id)


def sort_entries(entries: Iterable[TimelineEntry]) -> list[TimelineEntry]:
    return sorted(entries, key=_sort_key)


def dedupe_entries(
    entries: Iterable[TimelineEntry], *, window: timedelta = DEDUPE_WINDOW
) -> list[TimelineEntry]:
    """Collapse same-enrollment, non-money entries inside ``window``.

    Clusters are built oldest first; an entry joins the open cluster of its
    enrollment when it is within ``window`` of that cluster's FIRST entry (so
    a slow trickle of events never chains into one giant row).
    """
    passthrough: list[TimelineEntry] = []
    by_enrollment: dict[str, list[TimelineEntry]] = {}
    for e in entries:
        if e.kind == "money" or not e.enrollment_id:
            passthrough.append(e)
        else:
            by_enrollment.setdefault(e.enrollment_id, []).append(e)

    out = list(passthrough)
    for group in by_enrollment.values():
        group.sort(key=lambda e: (as_utc(e.at), e.entry_id))
        clusters: list[list[TimelineEntry]] = []
        for e in group:
            if clusters and as_utc(e.at) - as_utc(clusters[-1][0].at) <= window:
                clusters[-1].append(e)
            else:
                clusters.append([e])
        for cluster in clusters:
            if len(cluster) == 1:
                out.append(cluster[0])
                continue
            keep = min(
                cluster,
                key=lambda e: (
                    _KEEP_PRIORITY.get(e.kind, 9),
                    -as_utc(e.at).timestamp(),
                    e.entry_id,
                ),
            )
            others = tuple(e.code for e in cluster if e is not keep)
            out.append(replace(keep, collapsed_codes=keep.collapsed_codes + others))
    return out


def merge_timeline(
    sources: Iterable[Sequence[TimelineEntry]], *, cap: int = TIMELINE_CAP
) -> list[TimelineEntry]:
    """Every source's entries, deduped by id and by enrollment window, newest first, capped."""
    seen: set[str] = set()
    flat: list[TimelineEntry] = []
    for entries in sources:
        for e in entries:
            if e.entry_id in seen:
                continue
            seen.add(e.entry_id)
            flat.append(replace(e, at=as_utc(e.at)))
    return sort_entries(dedupe_entries(flat))[:cap]


# ------------------------------------------------------------------ paging


@dataclass(frozen=True)
class TimelineCursor:
    """Where the previous page ended: its last entry's time and id."""

    at: datetime
    entry_id: str

    def encode(self) -> str:
        raw = f"{as_utc(self.at).isoformat()}|{self.entry_id}".encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @classmethod
    def decode(cls, token: str) -> TimelineCursor:
        """Raises ``ValueError`` on anything that is not a cursor we issued."""
        try:
            padded = token + "=" * (-len(token) % 4)
            raw = base64.urlsafe_b64decode(padded.encode()).decode()
            at_text, entry_id = raw.split("|", 1)
            at = datetime.fromisoformat(at_text)
        except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
            raise ValueError("invalid timeline cursor") from exc
        if not entry_id:
            raise ValueError("invalid timeline cursor")
        return cls(at=as_utc(at), entry_id=entry_id)


def is_after_cursor(entry: TimelineEntry, cursor: TimelineCursor) -> bool:
    """True when ``entry`` sorts strictly after ``cursor`` (is older)."""
    return _sort_key(entry) > (-as_utc(cursor.at).timestamp(), cursor.entry_id)


def paginate(
    entries: Sequence[TimelineEntry], *, before: TimelineCursor | None, limit: int
) -> tuple[list[TimelineEntry], TimelineCursor | None]:
    """One page of an already sorted feed, and the cursor of the next page."""
    limit = max(1, min(limit, MAX_PAGE_SIZE))
    rest = [e for e in entries if before is None or is_after_cursor(e, before)]
    page = rest[:limit]
    if len(rest) > limit:
        last = page[-1]
        return page, TimelineCursor(at=last.at, entry_id=last.entry_id)
    return page, None


# ------------------------------------------------------------------ money


def _drop_money_segments(text: str) -> str:
    return " · ".join(s for s in text.split(" · ") if "$" not in s)


#: What a redacted money row says when its whole first segment was an amount.
_REDACTED_LEADS: dict[str, str] = {
    "payment_received": "Payment received",
    "charge_failed": "Card declined",
}


def redact_money(entry: TimelineEntry) -> TimelineEntry:
    """The entry as a caller who may not see amounts gets it (#553)."""
    carries_amount = entry.amount_cents is not None or entry.refunded_cents is not None
    if entry.kind != "money" and not carries_amount and "$" not in entry.summary:
        return entry
    summary = _drop_money_segments(entry.summary)
    lead = _REDACTED_LEADS.get(entry.code)
    if lead and not summary.startswith(lead):
        summary = f"{lead} · {summary}" if summary else lead
    if not summary:
        summary = entry.code.replace("_", " ").replace(":", " ").strip().capitalize()
    reason = None if entry.reason is not None and "$" in entry.reason else entry.reason
    detail = None if entry.detail is not None and "$" in entry.detail else entry.detail
    return replace(
        entry,
        summary=summary,
        amount_cents=None,
        refunded_cents=None,
        reason=reason,
        detail=detail,
    )


# ------------------------------------------------------------------ admin audit

#: Spec §5 "admin": the ``audit_logs`` actions the family timeline shows.
#: Anything not listed (``user_logged_in``, login provisioning, ...) is left
#: out on purpose; add an action here, with its label, to show it.
AUDIT_ACTION_ALLOWLIST: dict[str, str] = {
    "user.edited": "Parent profile edited",
    "user.role_changed": "Roles changed",
    "user.role_added": "Role added",
    "user.role_removed": "Role removed",
    "student.edited": "Child profile edited",
    "student.parent_changed": "Child moved family",
    "student.pathway_placed": "Pathway level placed",
    "billing.stripe_reconcile": "Stripe payment reconciled",
}
