"""One-off reconciliation: recompute ``sessions.reserved_seats`` from
actual active enrollment counts.

Context (issue #523): before PR #500, parent self-cancel flipped the
enrollment to ``cancelled`` without releasing the seat or emitting
``EnrollmentCancelled``. Every session where a parent self-cancelled
before the fix still carries an over-counted ``reserved_seats``,
silently rejecting new enrollments and never promoting the waitlist.
PR #500 fixed the go-forward path but shipped no backfill — this script
is that backfill.

For each session in the academy it:
  1. Recomputes the expected seat count as the number of enrollments
     with ``status == "active"`` for that session.
  2. Reports the per-session delta (and totals) BEFORE applying.
  3. Unless ``--dry-run``, applies the corrected count via a CAS write
     (matched on the observed ``reserved_seats`` value) so a concurrent
     production reserve/release is never clobbered — a lost CAS is
     reported and left for a re-run.
  4. For sessions that regained capacity, runs the production
     ``PromoteFromWaitlist`` use case (the same one the
     ``EnrollmentCancelled`` handler in
     ``backend/v2/composition/event_handlers.py`` calls) in a loop until
     the waitlist is drained or the session is full again.

Idempotent: a second run finds zero deltas and an empty/full waitlist.

Usage:
    source backend/.venv/bin/activate
    python -m backend.scripts.reconcile_reserved_seats \\
        --academy-id blno [--dry-run] [--skip-promotion]
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

if __file__.startswith("<"):
    ROOT = Path.cwd()
else:
    ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / "backend" / ".env")

import motor.motor_asyncio  # noqa: E402

from backend.v2.contexts.enrollment.application.use_cases.promote_from_waitlist import (  # noqa: E402
    PromoteFromWaitlist,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_event_repo import (  # noqa: E402
    MongoEnrollmentEventRepository,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_writer import (  # noqa: E402
    MongoEnrollmentWriter,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_session_writer import (  # noqa: E402
    MongoSessionWriter,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_waitlist_repo import (  # noqa: E402
    MongoWaitlistRepository,
)
from backend.v2.shared.config import get_settings  # noqa: E402
from backend.v2.shared.events import MongoOutbox  # noqa: E402
from backend.v2.shared.tenancy.context import tenant_scope  # noqa: E402

logger = logging.getLogger(__name__)

SESSIONS_COLLECTION = "sessions"
ENROLLMENTS_COLLECTION = "enrollments"
WAITLIST_COLLECTION = "waitlist"

# Mirrors MongoSessionWriter.try_reserve_seat — only these session states
# can hold reservations, so only these are worth promoting into.
ENROLLABLE_SESSION_STATUSES = {"scheduled", "active", "open"}

RECONCILE_REASON = "reserved_seats_reconciliation_pr500_backfill"


def session_delta_row(doc: dict[str, Any], active_count: int) -> dict[str, Any]:
    """Pure per-session delta computation (also used by tests)."""
    reserved = int(doc.get("reserved_seats") or 0)
    capacity = doc.get("capacity")
    if capacity is None:
        capacity = doc.get("max_students")
    return {
        "session_id": str(doc.get("session_id") or doc.get("_id")),
        "title": doc.get("title") or "",
        "status": doc.get("status") or "",
        "capacity": capacity,
        "reserved_seats": reserved,
        "active_enrollments": active_count,
        "delta": reserved - active_count,
    }


async def _active_counts_by_session(db: Any, academy_id: str) -> dict[str, int]:
    pipeline = [
        {"$match": {"academy_id": academy_id, "status": "active"}},
        {"$group": {"_id": "$session_id", "count": {"$sum": 1}}},
    ]
    return {
        str(row["_id"]): int(row["count"])
        async for row in db[ENROLLMENTS_COLLECTION].aggregate(pipeline)
    }


async def _apply_correction(db: Any, doc: dict[str, Any], expected: int) -> bool:
    """CAS the observed reserved_seats value to the recomputed one.

    Returns False when a concurrent writer changed the counter between the
    read and this write — the caller reports it and a re-run picks it up.
    """
    cas_filter: dict[str, Any] = {"_id": doc["_id"]}
    if "reserved_seats" in doc:
        cas_filter["reserved_seats"] = doc["reserved_seats"]
    else:
        cas_filter["reserved_seats"] = {"$exists": False}
    result = await db[SESSIONS_COLLECTION].update_one(
        cas_filter, {"$set": {"reserved_seats": expected}}
    )
    return result.matched_count == 1


async def _promote_until_settled(db: Any, academy_id: str, session_id: str) -> int:
    """Run the production FIFO promotion loop for one session.

    Each successful pass either reserves a freed seat for the oldest
    waiting entry or re-attaches an already-active enrollment; it stops
    when the waitlist is empty or ``try_reserve_seat`` finds the session
    full again. Emits ``WaitlistPromoted`` through the real outbox so
    downstream notification handlers fire exactly as in production.
    """
    with tenant_scope(academy_id):
        promote = PromoteFromWaitlist(
            waitlist=MongoWaitlistRepository(db),
            sessions=MongoSessionWriter(db),
            enrollments=MongoEnrollmentWriter(db),
            outbox=MongoOutbox(db),
            enrollment_events=MongoEnrollmentEventRepository(db),
            academy_id=lambda: academy_id,
        )
        promoted = 0
        while await promote.execute(session_id, reason=RECONCILE_REASON) is not None:
            promoted += 1
        return promoted


async def reconcile_reserved_seats(
    db: Any,
    *,
    academy_id: str,
    dry_run: bool,
    skip_promotion: bool = False,
) -> dict[str, Any]:
    """Run one reconciliation pass against an injected database."""
    sessions: list[dict[str, Any]] = (
        await db[SESSIONS_COLLECTION].find({"academy_id": academy_id}).to_list(length=None)
    )
    active_counts = await _active_counts_by_session(db, academy_id)

    rows = [
        session_delta_row(doc, active_counts.get(str(doc.get("session_id") or doc.get("_id")), 0))
        for doc in sessions
    ]
    drifted = [r for r in rows if r["delta"] != 0]

    # -----------------------------------------------------------------
    # Report BEFORE applying anything.
    # -----------------------------------------------------------------
    mode_label = "[DRY RUN] Would correct" if dry_run else "Correcting"
    print("\n=== RESERVED SEATS RECONCILIATION ===")
    print(f"Academy: {academy_id}")
    print(f"Sessions inspected: {len(rows)}")
    print(f"Sessions consistent: {len(rows) - len(drifted)}")
    print(f"Sessions drifted: {len(drifted)}")
    if drifted:
        header = (
            f"{'Session':<28} | {'Title':<24} | {'Cap':>4} | "
            f"{'Reserved':>8} | {'Active':>6} | {'Delta':>5}"
        )
        print(f"\n{mode_label}:")
        print(header)
        print("-" * len(header))
        for r in drifted:
            print(
                f"{r['session_id'][:26]:<28} | {str(r['title'])[:22]:<24} | "
                f"{r['capacity']!s:>4} | {r['reserved_seats']:>8} | "
                f"{r['active_enrollments']:>6} | {r['delta']:>+5}"
            )

    corrected = 0
    cas_lost: list[str] = []
    promotions: dict[str, int] = {}

    if not dry_run:
        doc_by_id = {str(doc.get("session_id") or doc.get("_id")): doc for doc in sessions}
        for r in drifted:
            doc = doc_by_id[r["session_id"]]
            if await _apply_correction(db, doc, r["active_enrollments"]):
                corrected += 1
            else:
                cas_lost.append(r["session_id"])
                logger.warning(
                    "reserved_seats CAS lost for session_id=%s — re-run to pick it up",
                    r["session_id"],
                )

        if not skip_promotion:
            # Promote wherever a seat is (now) free — not just the drifted
            # sessions: a pre-fix cancel followed by a manual counter edit
            # still left the waitlist un-promoted.
            for r in rows:
                if r["session_id"] in cas_lost:
                    continue
                if r["status"] not in ENROLLABLE_SESSION_STATUSES:
                    continue
                capacity = r["capacity"]
                if capacity is None or r["active_enrollments"] >= int(capacity):
                    continue
                waiting = await db[WAITLIST_COLLECTION].count_documents(
                    {
                        "academy_id": academy_id,
                        "session_id": r["session_id"],
                        "status": "waiting",
                    }
                )
                if waiting == 0:
                    continue
                promoted = await _promote_until_settled(db, academy_id, r["session_id"])
                if promoted:
                    promotions[r["session_id"]] = promoted

    print("\n=== RESULT ===")
    if dry_run:
        print("Dry run — no writes performed, no promotions triggered.")
    else:
        print(f"Sessions corrected: {corrected}")
        print(f"CAS lost (re-run needed): {len(cas_lost)}")
        for session_id in cas_lost:
            print(f"  CAS LOST: {session_id}")
        total_promoted = sum(promotions.values())
        print(f"Waitlist promotions: {total_promoted}")
        for session_id, count in sorted(promotions.items()):
            print(f"  {session_id}: promoted {count}")

    return {
        "inspected": len(rows),
        "drifted": drifted,
        "corrected": corrected,
        "cas_lost": cas_lost,
        "promotions": promotions,
    }


async def run(*, academy_id: str, dry_run: bool, skip_promotion: bool) -> int:
    s = get_settings()
    client: motor.motor_asyncio.AsyncIOMotorClient[Any] = motor.motor_asyncio.AsyncIOMotorClient(
        s.mongo_url
    )
    db = client[s.mongo_db]
    try:
        result = await reconcile_reserved_seats(
            db,
            academy_id=academy_id,
            dry_run=dry_run,
            skip_promotion=skip_promotion,
        )
    finally:
        client.close()
    return len(result["cas_lost"])


async def main(*, academy_id: str, dry_run: bool, skip_promotion: bool) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    unresolved = await run(academy_id=academy_id, dry_run=dry_run, skip_promotion=skip_promotion)
    if unresolved > 0:
        sys.exit(1)


if __name__ == "__main__":
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(
        description=(
            "Reconcile sessions.reserved_seats with actual active enrollment "
            "counts and promote waitlists for regained capacity (issue #523)."
        )
    )
    parser.add_argument("--academy-id", required=True, help="Academy ID to reconcile")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report deltas without writing or promoting",
    )
    parser.add_argument(
        "--skip-promotion",
        action="store_true",
        help="Correct counters but do not trigger waitlist promotion",
    )
    args = parser.parse_args()
    asyncio.run(
        main(
            academy_id=args.academy_id,
            dry_run=args.dry_run,
            skip_promotion=args.skip_promotion,
        )
    )
