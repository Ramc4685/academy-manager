#!/usr/bin/env python3
"""Audit — and, only when explicitly told to, repair — session rows stamped
with the admin form's ``timezone: "UTC"`` default.

Read-only by default. The repair itself lives in
``backend/v2/migrations/0160_session_timezone_utc_default_repair.py``; this
script is the reviewed execution path for it, plus the blast-radius and
billing-impact report a human needs before deciding to run it.

Why a script and not just the boot migration: migration ``0160``'s ``up()`` is
report-only unless ``SESSION_TZ_REPAIR_APPLY=1``, because the boot runner would
otherwise apply a financially-material rewrite on the next deploy unattended —
and would then record the version as applied, so a later flag flip would never
re-trigger it. Run this instead.

    # read-only report against a copy/staging restore
    scripts/prod/repair_session_timezones.py --mongo-url mongodb://127.0.0.1:27017 \
        --db-name academy_manager_saas_staging

    # after review, apply
    scripts/prod/repair_session_timezones.py --mongo-url ... --db-name ... \
        --apply --i-know-this-is-production

Financial records are never touched. Section 5 of the report only *lists*
invoices computed from an affected session; correcting them is a human call.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "mongo"})


def _load_migration() -> Any:
    import importlib

    return importlib.import_module("backend.v2.migrations.0160_session_timezone_utc_default_repair")


def _ulid_created_at(value: str) -> datetime | None:
    """Decode the millisecond timestamp out of a ULID.

    ``sessions`` rows carry no ``created_at`` — ``MongoSessionWriter.create``
    persists the domain model as-is — but ``session_id`` is a ULID, whose first
    10 Crockford-base32 characters are the creation time. That is the only
    creation date this collection has.
    """
    text = str(value or "").strip().upper()
    if len(text) < 10:
        return None
    millis = 0
    for char in text[:10]:
        index = _CROCKFORD.find(char)
        if index < 0:
            return None
        millis = millis * 32 + index
    try:
        return datetime.fromtimestamp(millis / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _is_recurring(doc: dict[str, Any]) -> bool:
    return bool(doc.get("days_of_week") and doc.get("start_time") and doc.get("end_time"))


def _host_is_local(mongo_url: str) -> bool:
    import urllib.parse

    parsed = urllib.parse.urlparse(mongo_url)
    if parsed.scheme != "mongodb":
        return False
    netloc = parsed.netloc.rsplit("@", 1)[-1]
    hosts = []
    for part in netloc.split(","):
        part = part.strip()
        if part.startswith("["):
            end = part.find("]")
            hosts.append(part[1:end].lower() if end != -1 else "")
        else:
            hosts.append(part.split(":", 1)[0].lower())
    return bool(hosts) and all(host in _LOCAL_HOSTS for host in hosts)


def _rule(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


async def _report_academies(db) -> dict[str, str | None]:
    _rule("1. Academies and their own timezone (`academies.timezone`)")
    print(
        "This is the field the admin form reads via GET /api/v2/admin/academy\n"
        "(GetAcademyUseCase). `academy_settings.timezone` is a *different* doc and\n"
        "is not what the form used — it is shown only where it disagrees.\n"
    )
    settings: dict[str, str] = {}
    async for doc in db["academy_settings"].find({}, {"academy_id": 1, "timezone": 1}):
        settings[str(doc.get("academy_id") or "")] = str(doc.get("timezone") or "") or "-"

    resolved: dict[str, str | None] = {}
    async for doc in db["academies"].find({}, {"academy_id": 1, "display_name": 1, "timezone": 1}):
        academy_id = str(doc.get("academy_id") or "")
        timezone = str(doc.get("timezone") or "").strip() or None
        resolved[academy_id] = timezone
        flag = ""
        if timezone is None:
            flag = "  <-- NO TIMEZONE: needs a human decision"
        elif timezone == "UTC":
            flag = (
                "  <-- reads UTC; note upsert_defaults() seeds new academies with "
                '"UTC", so this is not proof the academy is really UTC'
            )
        setting = settings.get(academy_id)
        mismatch = ""
        if setting and setting != (timezone or "-"):
            mismatch = f"  (academy_settings.timezone={setting!r} DISAGREES)"
        print(
            f"  {academy_id:<28} {timezone!s:<20} {doc.get('display_name') or ''!s}{flag}{mismatch}"
        )
    if not resolved:
        print("  (no academies found)")
    return resolved


async def _report_blast_radius(db, academy_timezones: dict[str, str | None]) -> list[dict]:
    _rule('2. Blast radius: session docs with timezone == "UTC"')
    total = await db["sessions"].count_documents({})
    affected: list[dict] = [doc async for doc in db["sessions"].find({"timezone": "UTC"})]
    missing = await db["sessions"].count_documents(
        {"$or": [{"timezone": {"$exists": False}}, {"timezone": None}, {"timezone": ""}]}
    )
    print(f"  sessions total                : {total}")
    print(f'  sessions with timezone "UTC"  : {len(affected)}')
    print(f"  sessions with no timezone     : {missing}   (different bug; readers fall")
    print("                                     back to America/Chicago — not repaired here)")

    by_academy: Counter[str] = Counter()
    by_shape: Counter[str] = Counter()
    by_month: Counter[str] = Counter()
    by_academy_shape: dict[str, Counter[str]] = defaultdict(Counter)
    for doc in affected:
        academy_id = str(doc.get("academy_id") or "(none)")
        shape = "recurring" if _is_recurring(doc) else "dated/one-off"
        by_academy[academy_id] += 1
        by_shape[shape] += 1
        by_academy_shape[academy_id][shape] += 1
        created = doc.get("created_at")
        if not isinstance(created, datetime):
            created = _ulid_created_at(str(doc.get("session_id") or ""))
        by_month[created.strftime("%Y-%m") if created else "unknown"] += 1

    print("\n  By academy (and whether the academy's own timezone makes it repairable):")
    for academy_id, count in by_academy.most_common():
        academy_tz = academy_timezones.get(academy_id, "(academy not found)")
        if academy_tz is None:
            verdict = "INDETERMINATE - academy has no timezone"
        elif academy_tz == "UTC":
            verdict = "INDETERMINATE - academy reads UTC too"
        elif academy_id not in academy_timezones:
            verdict = "INDETERMINATE - academy doc missing"
        else:
            verdict = f"repairable -> {academy_tz}"
        shapes = ", ".join(f"{k}={v}" for k, v in sorted(by_academy_shape[academy_id].items()))
        print(f"    {academy_id:<28} {count:>5}   [{shapes}]   {verdict}")

    print("\n  By shape:")
    for shape, count in by_shape.most_common():
        print(f"    {shape:<28} {count:>5}")

    print("\n  By creation month (from the session_id ULID unless created_at exists):")
    for month, count in sorted(by_month.items()):
        print(f"    {month:<28} {count:>5}")
    return affected


async def _report_billing_impact(db, affected: list[dict]) -> None:
    _rule("5. Billing / payroll impact — REPORT ONLY, nothing here is corrected")
    session_ids = [str(doc.get("session_id") or "") for doc in affected]
    session_ids = [sid for sid in session_ids if sid]
    if not session_ids:
        print("  No affected sessions, so no billing exposure.")
        return

    print(
        "  Why these are exposed: QuoteEnrollment and _resolve_charge_for_enrollment\n"
        "  both build the BillingPeriod from `session_doc['timezone']`, and\n"
        "  _session_occurrences builds every occurrence instant from it. With\n"
        "  timezone='UTC' the whole quote runs on a UTC clock, which can:\n"
        "    - label the period as the wrong month near local month-end;\n"
        "    - misjudge FirstMonthProrationPolicy's ELAPSED_BEFORE_ENROLLMENT and\n"
        "      SAME_DAY_CUTOFF tests, since the occurrence instant is hours off the\n"
        "      real class time, changing the prorated numerator and the amount.\n"
    )

    enrollments = [
        doc async for doc in db["enrollments"].find({"session_id": {"$in": session_ids}})
    ]
    enrollment_ids = [
        str(e.get("enrollment_id") or "") for e in enrollments if e.get("enrollment_id")
    ]
    print(f"  enrollments on affected sessions : {len(enrollments)}")

    snapshots = [
        doc
        async for doc in db["billing_calculation_snapshots"].find(
            {"session_id": {"$in": session_ids}}
        )
    ]
    utc_snapshots = [s for s in snapshots if str(s.get("timezone") or "") == "UTC"]
    print(
        f"  billing_calculation_snapshots    : {len(snapshots)} "
        f"({len(utc_snapshots)} computed with timezone='UTC')"
    )
    for snap in utc_snapshots[:50]:
        print(
            f"    snapshot={snap.get('snapshot_id')} status={snap.get('status')} "
            f"enrollment={snap.get('enrollment_id')} period={snap.get('billing_period_label')} "
            f"ratio={snap.get('proration_ratio')} amount_cents={snap.get('final_amount_cents')}"
        )
    if len(utc_snapshots) > 50:
        print(f"    ... and {len(utc_snapshots) - 50} more")

    for collection in ("payments", "ledger_payments"):
        if not enrollment_ids:
            break
        rows = [
            doc async for doc in db[collection].find({"enrollment_id": {"$in": enrollment_ids}})
        ]
        print(f"\n  {collection} for those enrollments : {len(rows)}")
        for row in rows[:50]:
            print(
                f"    id={row.get('payment_id') or row.get('_id')} "
                f"period={row.get('period')} status={row.get('status')} "
                f"amount_cents={row.get('amount_cents')} enrollment={row.get('enrollment_id')}"
            )
        if len(rows) > 50:
            print(f"    ... and {len(rows) - 50} more")

    print(
        "\n  DO NOT correct these automatically. Repairing the session timezone changes\n"
        "  what FUTURE quotes compute; it does not and must not retro-edit an invoice a\n"
        "  parent has already been shown or paid. Any correction is a credit/adjustment\n"
        "  decision for a human, per the billing safety rules in AGENTS.md."
    )


async def main_async(args: argparse.Namespace) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient

    migration = _load_migration()
    client = AsyncIOMotorClient(args.mongo_url)
    db = client[args.db_name]

    print(f"Mongo : {args.mongo_url.rsplit('@', 1)[-1]}")
    print(f"DB    : {args.db_name}")
    print(f"Mode  : {'APPLY (writes)' if args.apply else 'READ-ONLY report'}")

    academy_timezones = await _report_academies(db)
    affected = await _report_blast_radius(db, academy_timezones)

    _rule("3. What migration 0160 would change (dry run)")
    preview = await migration.repair(db, dry_run=True)
    print(f"  {preview.summary()}\n")
    for change in preview.sessions_changed:
        print(f"  SESSION    {change.describe()}")
    for change in preview.occurrences_changed:
        print(f"  OCCURRENCE {change.describe()}")

    _rule("4. Rows deliberately left alone (each needs a human decision or is safe)")
    if not preview.skipped:
        print("  (none)")
    for reason, rows in sorted(preview.skipped.items()):
        print(f"  {reason} ({len(rows)}):")
        for row in rows[:50]:
            print(f"    {row}")
        if len(rows) > 50:
            print(f"    ... and {len(rows) - 50} more")

    await _report_billing_impact(db, affected)

    if args.apply:
        _rule("APPLYING")
        result = await migration.repair(db, dry_run=False)
        print(f"  {result.summary()}")
    else:
        _rule("Nothing was written")
        print("  Re-run with --apply --i-know-this-is-production to write the repair.")

    client.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mongo-url",
        default=os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017"),
    )
    parser.add_argument("--db-name", default=os.environ.get("DB_NAME", "academy_manager_local"))
    parser.add_argument("--apply", action="store_true", help="write the repair (default: report)")
    parser.add_argument(
        "--i-know-this-is-production",
        action="store_true",
        help="required with --apply when the Mongo URL is not loopback",
    )
    args = parser.parse_args()

    if args.apply and not _host_is_local(args.mongo_url) and not args.i_know_this_is_production:
        raise SystemExit(
            "REFUSING: --apply against a non-local Mongo URL also requires "
            "--i-know-this-is-production. Take a backup first."
        )
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
