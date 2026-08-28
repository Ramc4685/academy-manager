"""Daily owner ops digest (issue #428).

Quarantined webhooks, dead-letter events, and dunning terminals accumulate in
Mongo with nothing pointing at them. This module assembles a small
cross-cutting snapshot and renders it as an email body; ``main.py`` owns the
cron job, the lease, and the Resend/stub send port.

Deliberately read-only, cross-tenant, and collection-name-driven (no repository
imports): the digest spans billing, events, and scheduler collections, so
binding it to any one context's repositories would drag a bounded context into
shared/. It is registered as a documented cross-tenant exception in
``v2/tests/test_no_raw_tenant_mongo_access.py``.

Attention-signal design — the subject line must stay actionable:

* ``quarantined`` is a terminal state that needs a human replay, but it is
  *all-time*: one unreplayed event from months ago would otherwise pin the
  subject to "attention needed" forever. The flag therefore uses the windowed
  count; the all-time total still appears in the body.
* ``failed`` is a *transient* retry state — most failed events self-heal on the
  next 60s drain tick — so the raw count is informational only. The flag uses
  the events whose ``next_retry_at`` is well past due, i.e. the ones that are
  genuinely stuck rather than mid-retry.
* Failed digest sends follow the same shape (issue #435): a send that still has
  retries left will very likely land on the next hourly tick, so only the ones
  that burned every attempt raise the flag. A run of those is the visible
  symptom of a Resend key that died after boot, when the boot-time credential
  check can no longer help.

``record_job_run`` is the one write: the monthly invoice generator stores its
totals under ``ops_job_runs`` so the digest can report them even though the
generator ran on a different tick (and possibly a different machine).
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

JOB_RUNS_COLLECTION = "ops_job_runs"

INVOICE_GENERATION_JOB = "generate_monthly_invoices"

LOOKBACK = timedelta(hours=24)
# A `failed` webhook event is mid-retry until its next_retry_at is well past
# due. The drain job ticks every 60s and the dedup backoff tops out well under
# an hour, so anything overdue by this much is stuck, not retrying.
FAILED_STALE_AFTER = timedelta(hours=1)

# Digest-send collections are read by collection name for the same reason the
# webhook counts are: this module deliberately imports no context repository.
DIGEST_SEND_COLLECTIONS = ("coach_digest_sends", "parent_digest_sends")
# Mirror of communications' MAX_DIGEST_SEND_ATTEMPTS. shared/ may not import a
# bounded context, so the value is duplicated here and pinned by
# ``test_ops_alerts.py::test_digest_attempt_ceiling_matches_the_domain``.
DIGEST_ATTEMPT_CEILING = 3


@dataclass(frozen=True)
class OpsDigestSnapshot:
    """Counts behind the daily ops digest. All counts are cross-academy."""

    generated_at: datetime
    lookback_hours: int
    webhooks_quarantined: int = 0
    webhooks_quarantined_recent: int = 0
    webhooks_failed: int = 0
    webhooks_failed_stale: int = 0
    dead_letter_total: int = 0
    dead_letter_recent: int = 0
    dunning_terminals_recent: int = 0
    digest_sends_failed: int = 0
    digest_sends_failed_exhausted: int = 0
    last_invoice_run: dict[str, Any] | None = None
    last_invoice_tick_at: datetime | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def has_attention_items(self) -> bool:
        """Only *actionable* signals raise the flag — see the module docstring."""
        return bool(
            self.webhooks_quarantined_recent
            or self.webhooks_failed_stale
            or self.dead_letter_recent
            or self.dunning_terminals_recent
            or self.digest_sends_failed_exhausted
            or self.errors
        )


async def record_job_run(
    db: AsyncIOMotorDatabase[Any],
    name: str,
    totals: dict[str, Any],
    *,
    meaningful: bool = True,
) -> None:
    """Store the last run summary for ``name`` so the digest can report it.

    ``meaningful=False`` records only the heartbeat: a daily job that ticked but
    had nothing to do (e.g. the invoice generator on the ~29 days a month when
    no academy's billing_day matches) must NOT overwrite the last real run's
    totals with zeros — those totals are the exact signal the digest exists to
    surface.

    Best-effort: a failure here must never abort the job that produced the
    totals.
    """
    now = datetime.now(UTC)
    update: dict[str, Any] = {"last_tick_at": now}
    if meaningful:
        update["totals"] = dict(totals)
        update["recorded_at"] = now
    try:
        await db[JOB_RUNS_COLLECTION].update_one({"_id": name}, {"$set": update}, upsert=True)
    except Exception:  # pragma: no cover - defensive
        log.warning("ops_job_run_record_failed job=%s", name, exc_info=True)


def webhook_status_pipeline(since: datetime, stale_before: datetime) -> list[dict[str, Any]]:
    """One pass over the open `stripe_webhook_events` for all four counts."""
    return [
        {"$match": {"status": {"$in": ["quarantined", "failed"]}}},
        {
            "$group": {
                "_id": "$status",
                "total": {"$sum": 1},
                "recent": {"$sum": {"$cond": [{"$gte": ["$last_attempt_at", since]}, 1, 0]}},
                "stale": {"$sum": {"$cond": [{"$lt": ["$next_retry_at", stale_before]}, 1, 0]}},
            }
        },
    ]


async def _webhook_counts(
    db: AsyncIOMotorDatabase[Any], since: datetime, stale_before: datetime
) -> dict[str, int]:
    counts = {
        "webhooks_quarantined": 0,
        "webhooks_quarantined_recent": 0,
        "webhooks_failed": 0,
        "webhooks_failed_stale": 0,
    }
    cursor = db["stripe_webhook_events"].aggregate(webhook_status_pipeline(since, stale_before))
    async for row in cursor:
        if row.get("_id") == "quarantined":
            counts["webhooks_quarantined"] = int(row.get("total") or 0)
            counts["webhooks_quarantined_recent"] = int(row.get("recent") or 0)
        elif row.get("_id") == "failed":
            counts["webhooks_failed"] = int(row.get("total") or 0)
            counts["webhooks_failed_stale"] = int(row.get("stale") or 0)
    return counts


async def _dead_letter_counts(db: AsyncIOMotorDatabase[Any], since: datetime) -> dict[str, int]:
    collection = db["dead_letter_events"]
    # Unfiltered total: the collection's own metadata, no scan.
    total = int(await collection.estimated_document_count())
    recent = int(await collection.count_documents({"created_at": {"$gte": since}}))
    return {"dead_letter_total": total, "dead_letter_recent": recent}


async def _dunning_terminal_count(db: AsyncIOMotorDatabase[Any], since: datetime) -> dict[str, int]:
    # Unindexed by design: every dunning_states index is academy_id-prefixed
    # (migration 0143) and this probe is deliberately cross-tenant. At current
    # volume (hundreds of rows) a daily collection scan is cheaper than
    # carrying an index that only this once-a-day query would use.
    count = await db["dunning_states"].count_documents(
        {"status": "dunned", "terminal_at": {"$gte": since}}
    )
    return {"dunning_terminals_recent": int(count)}


async def _digest_send_failure_counts(
    db: AsyncIOMotorDatabase[Any], since: datetime
) -> dict[str, int]:
    """Failed coach + parent digest sends in the window.

    ``digest_sends_failed`` includes rows that will retry on the next hourly
    tick; ``digest_sends_failed_exhausted`` counts only the ones that used every
    attempt, which is the number that means "someone lost their digest today".

    Rows flagged ``retryable: false`` are excluded from the actionable count:
    they are recipients with no e-mail address on file, a standing data problem
    that regenerates daily. Counting them would pin the digest's subject line to
    "attention needed" forever over something no send will ever fix. They still
    appear in the informational total and in the admin delivery log.
    """
    failed = 0
    exhausted = 0
    for name in DIGEST_SEND_COLLECTIONS:
        base = {"status": "failed", "created_at": {"$gte": since}}
        failed += int(await db[name].count_documents(base))
        exhausted += int(
            await db[name].count_documents(
                {
                    **base,
                    "attempt_count": {"$gte": DIGEST_ATTEMPT_CEILING},
                    # `$ne: False` so rows predating the field still count.
                    "retryable": {"$ne": False},
                }
            )
        )
    return {
        "digest_sends_failed": failed,
        "digest_sends_failed_exhausted": exhausted,
    }


async def collect_ops_digest(
    db: AsyncIOMotorDatabase[Any],
    *,
    now: datetime | None = None,
    lookback: timedelta = LOOKBACK,
) -> OpsDigestSnapshot:
    """Read the counts behind the digest.

    Probes run concurrently and each is isolated: one unreadable collection
    degrades to a note in ``errors`` rather than losing the whole digest — a
    partially readable database is exactly when the owner most needs the email.
    """
    generated_at = now or datetime.now(UTC)
    since = generated_at - lookback
    stale_before = generated_at - FAILED_STALE_AFTER

    probes: list[tuple[str, Any]] = [
        ("webhooks", _webhook_counts(db, since, stale_before)),
        ("dead_letter", _dead_letter_counts(db, since)),
        ("dunning_terminals", _dunning_terminal_count(db, since)),
        ("digest_sends", _digest_send_failure_counts(db, since)),
        ("last_invoice_run", _last_invoice_run(db)),
    ]
    results = await asyncio.gather(*(coro for _, coro in probes), return_exceptions=True)

    values: dict[str, int] = {}
    errors: list[str] = []
    last_invoice_run: dict[str, Any] | None = None
    last_invoice_tick_at: datetime | None = None
    for (label, _), result in zip(probes, results, strict=True):
        if isinstance(result, BaseException):
            errors.append(f"{label}: {result}")
            continue
        if label == "last_invoice_run":
            last_invoice_run = result.get("run") if result else None
            last_invoice_tick_at = result.get("last_tick_at") if result else None
            continue
        values.update(result)

    return OpsDigestSnapshot(
        generated_at=generated_at,
        lookback_hours=int(lookback.total_seconds() // 3600),
        last_invoice_run=last_invoice_run,
        last_invoice_tick_at=last_invoice_tick_at,
        errors=errors,
        **values,
    )


async def _last_invoice_run(db: AsyncIOMotorDatabase[Any]) -> dict[str, Any]:
    doc = await db[JOB_RUNS_COLLECTION].find_one({"_id": INVOICE_GENERATION_JOB})
    if not doc:
        return {}
    run = None
    if doc.get("totals") is not None or doc.get("recorded_at") is not None:
        run = {
            "recorded_at": doc.get("recorded_at"),
            "totals": dict(doc.get("totals") or {}),
        }
    return {"run": run, "last_tick_at": doc.get("last_tick_at")}


def render_ops_digest(snapshot: OpsDigestSnapshot) -> tuple[str, str]:
    """Return ``(subject, html_body)`` for the digest email.

    The date label is taken from ``generated_at`` verbatim, so the caller must
    pass a ``now`` in the scheduler timezone — a UTC stamp would put yesterday's
    date on a 07:00 email in any UTC+ deployment.
    """
    date_label = snapshot.generated_at.strftime("%Y-%m-%d")
    if snapshot.has_attention_items:
        subject = f"Ops digest {date_label} — attention needed"
    else:
        subject = f"Ops digest {date_label} — all clear"

    window = f"last {snapshot.lookback_hours}h"
    rows = [
        ("Stripe webhooks quarantined", snapshot.webhooks_quarantined_recent, window, True),
        ("Stripe webhooks quarantined", snapshot.webhooks_quarantined, "all time", False),
        ("Stripe webhooks failed (stuck)", snapshot.webhooks_failed_stale, "retry overdue", True),
        ("Stripe webhooks failed", snapshot.webhooks_failed, "incl. mid-retry", False),
        ("Dead-letter events", snapshot.dead_letter_recent, window, True),
        ("Dead-letter events", snapshot.dead_letter_total, "all time", False),
        ("Dunning terminals", snapshot.dunning_terminals_recent, window, True),
        (
            "Digest sends failed (no retries left)",
            snapshot.digest_sends_failed_exhausted,
            window,
            True,
        ),
        ("Digest sends failed", snapshot.digest_sends_failed, "incl. will-retry", False),
    ]
    row_html = "".join(
        f"<tr><td>{escape(label)}</td><td align='right'>"
        f"{f'<strong>{count}</strong>' if actionable else count}</td>"
        f"<td>{escape(note)}</td></tr>"
        for label, count, note, actionable in rows
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
        parts.append("<p>Nothing new needs attention in the last 24 hours.</p>")
    return subject, "".join(parts)


def _render_invoice_run(snapshot: OpsDigestSnapshot) -> str:
    """Job-level view of the invoice generator.

    Distinct from the per-(academy, period) rows in ``billing_generation_runs``,
    which drive the catch-up gate: this section answers "did the scheduled job
    run, and what did the last run that actually generated anything do". The
    heartbeat line is what makes a job that stopped ticking visible at all.
    """
    run = snapshot.last_invoice_run
    tick = snapshot.last_invoice_tick_at
    tick_line = f"<p>Last generation tick: {escape(_stamp(tick))}.</p>" if tick is not None else ""
    if not run:
        return f"<h3>Last invoice generation</h3><p>No recorded run.</p>{tick_line}"
    totals = run.get("totals") or {}
    when = _stamp(run.get("recorded_at"))
    if not totals:
        return f"<h3>Last invoice generation</h3><p>{escape(when)} — no counts recorded.</p>{tick_line}"
    items = "".join(
        f"<li>{escape(str(key))}: {escape(str(value))}</li>"
        for key, value in sorted(totals.items())
    )
    return f"<h3>Last invoice generation ({escape(when)})</h3><ul>{items}</ul>{tick_line}"


def _stamp(value: Any) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)
