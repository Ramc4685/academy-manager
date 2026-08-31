"""One-off repair (issue #593): re-run the #589 cancel cascade for
sessions that were cancelled *before* that fix reached production.

Context: before PR #589 (commit ``75262193``), ``CancelSession`` flipped
``sessions.status`` to ``"cancelled"`` but never touched the already
materialised ``session_occurrences``, which stayed ``status: "scheduled"``.
Every downstream reader keys off the OCCURRENCE status — coach payroll
(``mongo_payout_read_models``), the expected-payroll/revenue report
(``admin_reports_read_model``) and the coach day view
(``mongo_occurrence_repo``) — so those sessions keep showing up on coach
schedules and keep accruing expected pay, while the #589 listing filter
hides them from the admin sessions list so nobody can find them to
re-cancel by hand.

#589 fixed the go-forward path only. This script is the backfill.

What it does, per academy:
  1. Finds ``sessions`` with ``status: "cancelled"`` that still have
     ``session_occurrences`` at ``status: "scheduled"``, split into two
     buckets: FUTURE (``start_at >= now``, repairable) and PAST
     (``start_at < now``, reported only).
  2. Reports the before-count (per academy, per session) BEFORE writing.
  3. Unless ``--apply`` is passed it stops there — **dry run is the
     default**, and a missing/misspelled flag can only ever produce a dry
     run (argparse rejects an unknown flag and exits without writing).
  4. With ``--apply``, it loads the post-cancel session aggregate through
     the production ``MongoSessionWriter.get`` and feeds it into the very
     same ``maintain_session_occurrences`` closure the DELETE route calls
     (``backend/v2/interfaces/admin/sessions_routes.py``). No occurrence
     is written directly by this script.
  5. Re-counts and reports the after-count.

Why in-process instead of re-issuing ``DELETE /api/v2/admin/sessions/{id}``
(as issue #593 sketches): the DELETE route runs ``CancelSession`` first,
which re-emits ``EnrollmentCancelled`` for every still-active enrollment
and re-writes enrollment statuses. On sessions that are *already*
cancelled that is pure noise — duplicate outbox events, duplicate
waitlist-promotion handler runs, duplicate parent notifications. The
occurrence cascade is the only half that is missing, so the script drives
exactly that half, through the same composition-owned closure, with no
admin credentials and no HTTP surface involved.

Safety: the cascade only soft-cancels occurrences that pass the existing
``_is_clean_future_occurrence`` predicate — it rejects anything in the
past, anything not ``scheduled``, anything with a coach assigned, and
anything with attendance, coach attendance or a payout line. Attendance
history and earned coach pay cannot be rewritten, and nothing is ever
deleted: occurrences are soft-cancelled with
``cancellation_reason: "session_cancelled"``.

Occurrences the predicate protects are *expected* to survive the run and
are reported as "retained".

Idempotent: a second run soft-cancels nothing and reports zero sessions
repaired.

NOT COVERED — but REPORTED, loudly, because an audit that cannot see the
damage is worse than no audit:

* PAST occurrences left at ``"scheduled"``. A session cancelled months
  ago has its whole stranded run behind ``now``, so the future bucket is
  empty and a future-only report would call that session clean. It is
  not: ``effective_occurrence_status`` reads a past ``scheduled``
  occurrence as ``"completed"`` and
  ``MonthlyCoachOccurrenceReaderAdapter.coaches_with_occurrences`` selects
  exactly those rows, so the next payroll generation pays for a class
  that was cancelled and never taught. The cascade refuses to touch the
  past by design, so this script only counts and lists them — widening
  the WRITE to the past would be a change to #589's predicate and a
  money decision for the issue owner, not something to slip into a
  backfill.
* Payroll already GENERATED off any of these occurrences. A payout period
  already generated (or approved/paid) keeps whatever lines it was built
  from and needs separate attention.
* Cancelled sessions carrying no ``academy_id``: they cannot be
  tenant-scoped, so the cascade can never repair them. They are counted
  as failures and make the run exit non-zero rather than being logged
  away.

Usage:
    # dry run (default — writes nothing)
    backend/.venv/bin/python -m backend.scripts.recancel_half_cancelled_sessions

    # apply
    backend/.venv/bin/python -m backend.scripts.recancel_half_cancelled_sessions --apply

Add ``--academy-id <id>`` to restrict either mode to one academy.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

if __file__.startswith("<"):
    ROOT = Path.cwd()
else:
    ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / "backend" / ".env")

import motor.motor_asyncio  # noqa: E402

from backend.v2.composition.admin import compose_admin  # noqa: E402
from backend.v2.contexts.enrollment.infrastructure.mongo_session_writer import (  # noqa: E402
    MongoSessionWriter,
)
from backend.v2.shared.config import get_settings  # noqa: E402
from backend.v2.shared.events import MongoOutbox  # noqa: E402
from backend.v2.shared.idempotency.mongo_store import MongoIdempotencyStore  # noqa: E402
from backend.v2.shared.tenancy.context import tenant_scope  # noqa: E402

logger = logging.getLogger(__name__)

SESSIONS_COLLECTION = "sessions"
OCCURRENCES_COLLECTION = "session_occurrences"

PAYROLL_CAVEAT = (
    "NOTE: payroll ALREADY GENERATED from these occurrences is NOT corrected by "
    "this script. It repairs future accrual only — any payout period already "
    "generated, approved or paid keeps the lines it was built from and must be "
    "reviewed separately (see issue #593)."
)

PAST_OCCURRENCE_CAVEAT = (
    "WARNING: the sessions below still own PAST occurrences left at status "
    "'scheduled'. This script does NOT repair them — the #589 cascade refuses "
    "to touch the past on purpose — but they are not inert: "
    "`effective_occurrence_status` reads a past 'scheduled' occurrence as "
    "'completed', and `MonthlyCoachOccurrenceReaderAdapter` selects exactly "
    "those rows, so the NEXT payroll generation will pay for classes that were "
    "cancelled and never taught. Review these dates by hand before generating "
    "payroll for the periods they fall in."
)


def session_identity(doc: dict[str, Any]) -> str:
    """The id the occurrence rows point at (also used by tests)."""
    return str(doc.get("session_id") or doc.get("_id"))


def _occurrence_filter(
    *,
    academy_id: str,
    session_id: str,
    start_at: dict[str, Any],
) -> dict[str, Any]:
    """Occurrences of one session still advertising themselves as scheduled.

    Mirrors the read side of ``maintain_session_occurrences``: occurrences
    attach to a session by either ``session_id`` or ``template_session_id``,
    and a missing ``status`` is read as ``"scheduled"`` everywhere else in
    the codebase, so it counts here too.
    """
    return {
        "academy_id": academy_id,
        "start_at": start_at,
        "$and": [
            {"$or": [{"session_id": session_id}, {"template_session_id": session_id}]},
            {
                "$or": [
                    {"status": "scheduled"},
                    {"status": None},
                    {"status": {"$exists": False}},
                ]
            },
        ],
    }


def live_occurrence_filter(
    *,
    academy_id: str,
    session_id: str,
    now: datetime,
) -> dict[str, Any]:
    """FUTURE scheduled occurrences — the ones the cascade can repair."""
    return _occurrence_filter(academy_id=academy_id, session_id=session_id, start_at={"$gte": now})


def past_occurrence_filter(
    *,
    academy_id: str,
    session_id: str,
    now: datetime,
) -> dict[str, Any]:
    """PAST scheduled occurrences — reported, never repaired.

    The #589 cascade deliberately refuses to touch the past
    (``_is_clean_future_occurrence``), so this script cannot repair these
    either. They still matter: ``effective_occurrence_status`` reads a past
    ``scheduled`` occurrence as ``"completed"``, and
    ``MonthlyCoachOccurrenceReaderAdapter.coaches_with_occurrences`` matches
    ``{"status": {"$ne": "cancelled"}, "$or": [{"status": "completed"},
    {"end_at": {"$lt": now}}]}`` — so a stranded past occurrence under a
    cancelled session is counted as payable work by the NEXT payroll
    generation. Counting them is the whole point of an audit script: a
    session cancelled months ago has its entire stranded run in the past,
    and reporting only the future bucket would report that session as clean.
    """
    return _occurrence_filter(academy_id=academy_id, session_id=session_id, start_at={"$lt": now})


async def _count_live_occurrences(
    db: Any,
    *,
    academy_id: str,
    session_id: str,
    now: datetime,
) -> int:
    return int(
        await db[OCCURRENCES_COLLECTION].count_documents(
            live_occurrence_filter(academy_id=academy_id, session_id=session_id, now=now)
        )
    )


async def _count_past_occurrences(
    db: Any,
    *,
    academy_id: str,
    session_id: str,
    now: datetime,
) -> int:
    return int(
        await db[OCCURRENCES_COLLECTION].count_documents(
            past_occurrence_filter(academy_id=academy_id, session_id=session_id, now=now)
        )
    )


class SessionScan(NamedTuple):
    """What one pass over ``sessions`` found.

    ``skipped`` is not an empty category to be logged away: a cancelled
    session with no ``academy_id`` cannot be tenant-scoped, so the cascade
    can never repair it. It is surfaced in the report and counted towards
    a non-zero exit so the run can never look clean while leaving a broken
    session behind.
    """

    rows: list[dict[str, Any]]
    skipped: list[dict[str, Any]]


async def find_half_cancelled_sessions(
    db: Any,
    *,
    now: datetime,
    academy_id: str | None = None,
) -> SessionScan:
    """Cancelled sessions that still own ``scheduled`` occurrences.

    A session is reported when EITHER bucket is non-empty. Only the future
    bucket is repairable; the past bucket exists so a session whose whole
    stranded run is already in the past cannot be invisible to the audit.
    """
    query: dict[str, Any] = {"status": "cancelled"}
    if academy_id is not None:
        query["academy_id"] = academy_id

    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    cursor = db[SESSIONS_COLLECTION].find(query)
    async for doc in cursor:
        session_id = session_identity(doc)
        doc_academy = str(doc.get("academy_id") or "")
        if not doc_academy:
            logger.warning(
                "skipping session without academy_id: %s — cannot tenant-scope the cascade",
                session_id,
            )
            skipped.append(
                {
                    "academy_id": "",
                    "session_id": session_id,
                    "title": str(doc.get("title") or doc.get("name") or ""),
                    "reason": "no academy_id — cannot tenant-scope the cascade",
                }
            )
            continue
        future_count = await _count_live_occurrences(
            db, academy_id=doc_academy, session_id=session_id, now=now
        )
        past_count = await _count_past_occurrences(
            db, academy_id=doc_academy, session_id=session_id, now=now
        )
        if future_count == 0 and past_count == 0:
            continue
        rows.append(
            {
                "academy_id": doc_academy,
                "session_id": session_id,
                "title": str(doc.get("title") or doc.get("name") or ""),
                "future_scheduled": future_count,
                "past_scheduled": past_count,
            }
        )
    rows.sort(key=lambda r: (r["academy_id"], r["session_id"]))
    skipped.sort(key=lambda r: r["session_id"])
    return SessionScan(rows=rows, skipped=skipped)


def _build_cascade(db: Any) -> Any:
    """The production ``maintain_session_occurrences`` closure.

    Built through the real ``compose_admin`` so the repair runs the exact
    code path the DELETE route runs, guards included.

    The Stripe gateway is a required constructor argument for
    ``compose_admin`` but is never reached by the occurrence cascade, so
    the no-op fake is injected deliberately: it keeps the repair free of
    Stripe credentials and makes it structurally impossible for this
    script to issue a live Stripe call.
    """
    from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway

    admin = compose_admin(db, MongoOutbox(db), MongoIdempotencyStore(db), FakeStripeGateway())
    maintain = admin.maintain_session_occurrences
    if maintain is None:  # pragma: no cover - composition always wires it
        raise RuntimeError("compose_admin did not wire maintain_session_occurrences")
    return maintain


async def recancel_half_cancelled_sessions(
    db: Any,
    *,
    apply: bool,
    academy_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run one repair pass against an injected database."""
    cutoff = now or datetime.now(UTC)
    before_scan = await find_half_cancelled_sessions(db, now=cutoff, academy_id=academy_id)
    before_rows = before_scan.rows
    before_total = sum(int(r["future_scheduled"]) for r in before_rows)
    past_total = sum(int(r["past_scheduled"]) for r in before_rows)
    repairable_rows = [r for r in before_rows if int(r["future_scheduled"]) > 0]

    by_academy: dict[str, list[dict[str, Any]]] = {}
    for row in before_rows:
        by_academy.setdefault(row["academy_id"], []).append(row)

    # -----------------------------------------------------------------
    # Report BEFORE writing anything.
    # -----------------------------------------------------------------
    mode_label = "APPLY (writes enabled)" if apply else "DRY RUN (no writes)"
    print("\n=== HALF-CANCELLED SESSION OCCURRENCE REPAIR (issue #593) ===")
    print(f"Mode: {mode_label}")
    print(f"Academy filter: {academy_id or 'ALL academies'}")
    print(f"Cutoff (now, UTC): {cutoff.isoformat()}")
    print(f"Cancelled sessions with stranded scheduled occurrences: {len(before_rows)}")
    print(f"Future scheduled occurrences under cancelled sessions (before): {before_total}")
    print(f"PAST scheduled occurrences under cancelled sessions (NOT repaired): {past_total}")
    print(f"Cancelled sessions skipped (no academy_id): {len(before_scan.skipped)}")

    for acad in sorted(by_academy):
        rows = by_academy[acad]
        future_subtotal = sum(int(r["future_scheduled"]) for r in rows)
        past_subtotal = sum(int(r["past_scheduled"]) for r in rows)
        print(
            f"\nAcademy {acad}: {len(rows)} session(s), "
            f"{future_subtotal} future + {past_subtotal} past occurrence(s)"
        )
        header = f"  {'Session':<28} | {'Title':<28} | {'Future':>8} | {'Past':>8}"
        print(header)
        print("  " + "-" * (len(header) - 2))
        for r in rows:
            print(
                f"  {r['session_id'][:26]:<28} | {r['title'][:26]:<28} | "
                f"{r['future_scheduled']:>8} | {r['past_scheduled']:>8}"
            )

    if past_total:
        print(f"\n{PAST_OCCURRENCE_CAVEAT}")
        for r in before_rows:
            if int(r["past_scheduled"]):
                print(
                    f"  PAST {r['academy_id']}/{r['session_id']}: "
                    f"{r['past_scheduled']} occurrence(s) — needs manual payroll review"
                )

    repaired: list[dict[str, Any]] = []
    unchanged: list[dict[str, Any]] = []
    # A cancelled session with no academy_id cannot be repaired by anything
    # here, so it starts life as a failure rather than a log line.
    failed: list[dict[str, Any]] = list(before_scan.skipped)
    cancelled_total = 0
    after_total = before_total

    if apply and repairable_rows:
        maintain = _build_cascade(db)
        sessions_writer = MongoSessionWriter(db)
        for row in repairable_rows:
            acad = row["academy_id"]
            session_id = row["session_id"]
            try:
                with tenant_scope(acad):
                    session = await sessions_writer.get(session_id)
                    if session is None:
                        failed.append({**row, "reason": "session aggregate not found"})
                        continue
                    if session.status != "cancelled":
                        # Somebody un-cancelled it between the scan and now.
                        # Cascading here would wrongly kill a live session.
                        failed.append({**row, "reason": f"status is now {session.status!r}"})
                        continue
                    # Same call, same argument, as the DELETE route (#589).
                    await maintain(session)
                    after = await _count_live_occurrences(
                        db, academy_id=acad, session_id=session_id, now=cutoff
                    )
            # One bad session must not stop the run — record it and continue.
            except Exception as exc:
                logger.exception("repair failed for session_id=%s", session_id)
                failed.append({**row, "reason": f"{type(exc).__name__}: {exc}"})
                continue

            closed = int(row["future_scheduled"]) - after
            record = {**row, "after": after, "cancelled": closed}
            if closed > 0:
                cancelled_total += closed
                repaired.append(record)
            else:
                unchanged.append(record)

        # Re-derive the after-count from the database rather than from the
        # per-session bookkeeping, so a skipped or failed session is counted
        # as still-broken instead of silently dropping out of the total.
        after_scan = await find_half_cancelled_sessions(db, now=cutoff, academy_id=academy_id)
        after_total = sum(int(r["future_scheduled"]) for r in after_scan.rows)

    # -----------------------------------------------------------------
    print("\n=== RESULT ===")
    if not apply:
        print("Dry run — nothing was written. Re-run with --apply to repair.")
        print(
            "Occurrences protected by the cascade's safety predicate "
            "(attended / coach-assigned / on a payout line) will be RETAINED, "
            "so the after-count is not guaranteed to reach zero."
        )
    else:
        print(f"Sessions repaired: {len(repaired)}")
        print(f"Sessions with nothing left to repair: {len(unchanged)}")
        print(f"Occurrences soft-cancelled: {cancelled_total}")
        print(f"Future scheduled occurrences under cancelled sessions (after): {after_total}")
        # Only claim the tenant is clean when the PAST bucket is empty too and
        # nothing was skipped — otherwise "after: 0" reads as "nothing left to
        # do" while stranded past occurrences are still headed for payroll.
        if after_total and not failed and not past_total:
            print(
                "  All remaining rows were RETAINED on purpose — the cascade's "
                "safety predicate protects occurrences that are attended, "
                "coach-assigned, or already on a payout line."
            )
    print(f"PAST scheduled occurrences still needing manual review: {past_total}")
    if failed:
        print(f"Sessions skipped or failed: {len(failed)}")
        for row in failed:
            print(
                f"  SKIPPED {row['academy_id'] or '<no academy_id>'}/{row['session_id']}: {row['reason']}"
            )
    print(f"\n{PAYROLL_CAVEAT}")

    return {
        "applied": apply,
        "cutoff": cutoff,
        "sessions_found": len(before_rows),
        "before_total": before_total,
        "past_total": past_total,
        "after_total": after_total,
        "occurrences_cancelled": cancelled_total,
        "sessions_repaired": len(repaired),
        "rows": before_rows,
        "repaired": repaired,
        "unchanged": unchanged,
        "failed": failed,
        "skipped_no_academy": before_scan.skipped,
    }


async def run(*, apply: bool, academy_id: str | None) -> int:
    s = get_settings()
    client: motor.motor_asyncio.AsyncIOMotorClient[Any] = motor.motor_asyncio.AsyncIOMotorClient(
        s.mongo_url
    )
    db = client[s.mongo_db]
    try:
        result = await recancel_half_cancelled_sessions(
            db,
            apply=apply,
            academy_id=academy_id,
        )
    finally:
        client.close()
    return len(result["failed"])


async def main(*, apply: bool, academy_id: str | None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    unresolved = await run(apply=apply, academy_id=academy_id)
    if unresolved > 0:
        sys.exit(1)


def build_arg_parser() -> argparse.ArgumentParser:
    """CLI surface, at module scope so the dry-run default is testable."""
    parser = argparse.ArgumentParser(
        description=(
            "Re-run the #589 cancel cascade for sessions cancelled before that "
            "fix deployed, so their future occurrences stop accruing expected "
            "coach pay (issue #593). Dry run unless --apply is passed."
        )
    )
    parser.add_argument(
        "--academy-id",
        default=None,
        help="Restrict the scan/repair to one academy (default: every academy)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Actually run the cascade. WITHOUT this flag the script is a dry "
            "run and writes nothing."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicit dry run (the default). Wins over --apply when both are passed.",
    )
    return parser


def apply_requested(args: argparse.Namespace) -> bool:
    """Writes happen only on an explicit, correctly spelled ``--apply``.

    Anything else — no flag, ``--dry-run``, both flags together — is a dry
    run. A misspelled flag never reaches here: argparse rejects unknown
    arguments and exits before any database work starts.
    """
    return bool(args.apply) and not bool(args.dry_run)


if __name__ == "__main__":
    import asyncio

    parsed = build_arg_parser().parse_args()
    asyncio.run(
        main(
            apply=apply_requested(parsed),
            academy_id=parsed.academy_id,
        )
    )
