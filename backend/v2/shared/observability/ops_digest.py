"""Daily owner ops digest (issue #428).

Quarantined webhooks, dead-letter events, and dunning terminals accumulate in
Mongo with nothing pointing at them. This module assembles a small
cross-cutting snapshot and renders it as an email body; ``main.py`` owns the
cron job, the lease, and the Resend/stub send port.

Deliberately read-only and collection-name-driven (no repository imports): the
digest spans billing, events, and scheduler collections, so binding it to any
one context's repositories would drag a bounded context into shared/.

``record_job_run`` is the one write — the monthly invoice generator stores its
last totals under ``ops_job_runs`` so the digest can report them even though
the generator ran on a different tick (and possibly a different machine).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from html import escape
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

log = logging.getLogger(__name__)

JOB_RUNS_COLLECTION = "ops_job_runs"
STRIPE_WEBHOOK_EVENTS = "stripe_webhook_events"
DEAD_LETTER_EVENTS = "dead_letter_events"
DUNNING_STATES = "dunning_states"

INVOICE_GENERATION_JOB = "generate_monthly_invoices"

LOOKBACK = timedelta(hours=24)


@dataclass(frozen=True)
class OpsDigestSnapshot:
    """Counts behind the daily ops digest. All counts are cross-academy."""

    generated_at: datetime
    lookback_hours: int
    webhooks_quarantined: int = 0
    webhooks_failed: int = 0
    dead_letter_total: int = 0
    dead_letter_recent: int = 0
    dunning_terminals_recent: int = 0
    last_invoice_run: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def has_attention_items(self) -> bool:
        return bool(
            self.webhooks_quarantined
            or self.webhooks_failed
            or self.dead_letter_recent
            or self.dunning_terminals_recent
            or self.errors
        )


async def record_job_run(
    db: AsyncIOMotorDatabase[Any],
    name: str,
    totals: dict[str, Any],
) -> None:
    """Store the last run summary for ``name`` so the digest can report it.

    Best-effort: a failure here must never abort the job that produced the
    totals.
    """
    try:
        await db[JOB_RUNS_COLLECTION].update_one(
            {"_id": name},
            {"$set": {"totals": dict(totals), "recorded_at": datetime.now(UTC)}},
            upsert=True,
        )
    except Exception:  # pragma: no cover - defensive
        log.warning("ops_job_run_record_failed job=%s", name, exc_info=True)


async def _count(db: AsyncIOMotorDatabase[Any], collection: str, query: dict[str, Any]) -> int:
    return int(await db[collection].count_documents(query))


async def collect_ops_digest(
    db: AsyncIOMotorDatabase[Any],
    *,
    now: datetime | None = None,
    lookback: timedelta = LOOKBACK,
) -> OpsDigestSnapshot:
    """Read the counts behind the digest.

    Each probe is isolated: one unreadable collection degrades to a note in
    ``errors`` rather than losing the whole digest — a partially readable
    database is exactly when the owner most needs the email.
    """
    generated_at = now or datetime.now(UTC)
    since = generated_at - lookback
    values: dict[str, int] = {}
    errors: list[str] = []

    probes: list[tuple[str, str, dict[str, Any]]] = [
        ("webhooks_quarantined", STRIPE_WEBHOOK_EVENTS, {"status": "quarantined"}),
        ("webhooks_failed", STRIPE_WEBHOOK_EVENTS, {"status": "failed"}),
        ("dead_letter_total", DEAD_LETTER_EVENTS, {}),
        ("dead_letter_recent", DEAD_LETTER_EVENTS, {"created_at": {"$gte": since}}),
        (
            "dunning_terminals_recent",
            DUNNING_STATES,
            {"status": "dunned", "terminal_at": {"$gte": since}},
        ),
    ]
    for key, collection, query in probes:
        try:
            values[key] = await _count(db, collection, query)
        except Exception as exc:
            errors.append(f"{key}: {exc}")
            values[key] = 0

    last_invoice_run: dict[str, Any] | None = None
    try:
        doc = await db[JOB_RUNS_COLLECTION].find_one({"_id": INVOICE_GENERATION_JOB})
        if doc:
            last_invoice_run = {
                "recorded_at": doc.get("recorded_at"),
                "totals": dict(doc.get("totals") or {}),
            }
    except Exception as exc:
        errors.append(f"last_invoice_run: {exc}")

    return OpsDigestSnapshot(
        generated_at=generated_at,
        lookback_hours=int(lookback.total_seconds() // 3600),
        last_invoice_run=last_invoice_run,
        errors=errors,
        **values,
    )


def render_ops_digest(snapshot: OpsDigestSnapshot) -> tuple[str, str]:
    """Return ``(subject, html_body)`` for the digest email."""
    date_label = snapshot.generated_at.strftime("%Y-%m-%d")
    if snapshot.has_attention_items:
        subject = f"Ops digest {date_label} — attention needed"
    else:
        subject = f"Ops digest {date_label} — all clear"

    rows = [
        ("Stripe webhooks quarantined", snapshot.webhooks_quarantined, "open"),
        ("Stripe webhooks failed", snapshot.webhooks_failed, "open"),
        ("Dead-letter events", snapshot.dead_letter_total, "total"),
        (
            "Dead-letter events",
            snapshot.dead_letter_recent,
            f"last {snapshot.lookback_hours}h",
        ),
        (
            "Dunning terminals",
            snapshot.dunning_terminals_recent,
            f"last {snapshot.lookback_hours}h",
        ),
    ]
    row_html = "".join(
        f"<tr><td>{escape(label)}</td><td align='right'><strong>{count}</strong></td>"
        f"<td>{escape(window)}</td></tr>"
        for label, count, window in rows
    )

    parts = [
        f"<h2>Ops digest — {escape(date_label)}</h2>",
        "<table cellpadding='6' cellspacing='0' border='0'>",
        "<tr><th align='left'>Signal</th><th align='right'>Count</th>",
        "<th align='left'>Window</th></tr>",
        row_html,
        "</table>",
        _render_invoice_run(snapshot),
    ]
    if snapshot.errors:
        error_items = "".join(f"<li>{escape(item)}</li>" for item in snapshot.errors)
        parts.append(f"<h3>Digest collection errors</h3><ul>{error_items}</ul>")
    if not snapshot.has_attention_items:
        parts.append("<p>No quarantined webhooks, dead letters, or dunning terminals.</p>")
    return subject, "".join(parts)


def _render_invoice_run(snapshot: OpsDigestSnapshot) -> str:
    run = snapshot.last_invoice_run
    if not run:
        return "<h3>Last invoice generation</h3><p>No recorded run.</p>"
    recorded_at = run.get("recorded_at")
    when = recorded_at.isoformat() if isinstance(recorded_at, datetime) else str(recorded_at)
    totals = run.get("totals") or {}
    if not totals:
        return f"<h3>Last invoice generation</h3><p>{escape(when)} — no counts recorded.</p>"
    items = "".join(
        f"<li>{escape(str(key))}: {escape(str(value))}</li>"
        for key, value in sorted(totals.items())
    )
    return f"<h3>Last invoice generation ({escape(when)})</h3><ul>{items}</ul>"
