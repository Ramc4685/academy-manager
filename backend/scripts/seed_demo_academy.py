"""Seed, or reset, the fictional Demo Academy that app store reviewers sign in to.

The academy is served at ``demo-academy.courtmastr.com`` (slug ``demo-academy``,
id ``acad_demo_academy``) and has four email + password logins that share one
password: ``demo.owner``, ``demo.admin``, ``demo.coach`` and ``demo.parent``,
all ``@example.com``. Runbook: ``docs/runbooks/demo-academy.md``.

    python -m backend.scripts.seed_demo_academy           # dry run, writes nothing
    python -m backend.scripts.seed_demo_academy --apply   # writes

Reads ``MONGO_URL`` and ``DB_NAME``. ``--apply`` takes the password from
``DEMO_PASSWORD`` or a prompt; it is never printed, logged or stored.

Idempotent: every document has a fixed id, and a re-run replaces the seeded
documents and deletes anything else the demo academy has gained in the same
collections, so it also repairs a demo a reviewer has edited or deleted from.

Strictly scoped: every write names ``acad_demo_academy`` (``require_demo``
refuses anything else), plus the four logins' ``users`` rows, their Firebase
accounts and their ``email_suppressions`` rows. The suppressions are what keep
the demo quiet: ``hard_bounce`` makes the send gate drop every email to those
addresses. Nothing here can charge: there is no card, no Stripe customer, no
autopay and no connected account.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

from motor.motor_asyncio import AsyncIOMotorClient

from backend.scripts.seed_local import build_recurring_session_doc, build_session_occurrence_docs
from backend.v2.composition.platform_billing_identity import compose_invoice_prefix_assigner
from backend.v2.contexts.billing.domain.ledger import format_invoice_number
from backend.v2.contexts.identity.application.use_cases.bootstrap_academy import (
    BootstrapAcademy,
    BootstrapAcademyCommand,
)
from backend.v2.contexts.identity.infrastructure.mongo_bootstrap_store import (
    MongoTenantBootstrapStore,
)

DEMO_ACADEMY_ID = "acad_demo_academy"
SLUG = "demo-academy"
DOMAIN = f"{SLUG}.courtmastr.com"
NAME = "Demo Academy"
TZ = "America/Chicago"

#: persona -> (email, display name, membership roles). An owner holds owner + admin.
PERSONAS: dict[str, tuple[str, str, list[str]]] = {
    "owner": ("demo.owner@example.com", "Demo Owner", ["owner", "admin"]),
    "admin": ("demo.admin@example.com", "Demo Admin", ["admin"]),
    "coach": ("demo.coach@example.com", "Demo Coach", ["coach"]),
    "parent": ("demo.parent@example.com", "Demo Parent", ["parent"]),
}
DEMO_EMAILS = frozenset(email for email, _, _ in PERSONAS.values())

#: (email, password, display name) -> Firebase uid.
EnsureLogin = Callable[[str, str, str], str]


class DemoScopeError(RuntimeError):
    """A write would reach outside the demo academy."""


def require_demo(academy_id: object) -> None:
    if academy_id != DEMO_ACADEMY_ID:
        raise DemoScopeError(f"refusing to write academy {academy_id!r}; only {DEMO_ACADEMY_ID}")


def firebase_ensure_login(email: str, password: str, display_name: str) -> str:
    """Create or reset the Firebase account. Looks up by email first: prod has
    email-enumeration protection, and ``get_user_by_email`` is the call that
    still answers ``UserNotFoundError`` cleanly."""
    from firebase_admin import auth

    from backend.v2.contexts.identity.infrastructure.firebase_admin_adapter import firebase_app

    app = firebase_app()
    fields: dict[str, Any] = {
        "password": password,
        "display_name": display_name,
        "email_verified": True,
        "disabled": False,
        "app": app,
    }
    try:
        uid = auth.get_user_by_email(email, app=app).uid
    except auth.UserNotFoundError:
        return str(auth.create_user(email=email, **fields).uid)
    auth.update_user(uid, **fields)
    return str(uid)


def _user_id(persona: str) -> str:
    return f"demo_user_{persona}"


async def _refuse_foreign_academy(db: Any) -> None:
    """The slug or host already belonging to another academy (say one created
    at /platform/tenants) is a stop, not something to overwrite."""
    rows = [
        *await db["academies"]
        .find({"$or": [{"slug": SLUG}, {"primary_domain": DOMAIN}, {"custom_domain": DOMAIN}]})
        .to_list(None),
        *await db["academy_domains"].find({"domain": DOMAIN}).to_list(None),
    ]
    for row in rows:
        require_demo(row.get("academy_id"))


async def _refuse_foreign_user(db: Any, persona: str, email: str) -> dict[str, Any] | None:
    existing: dict[str, Any] | None = await db["users"].find_one(
        {"normalized_email": email}
    ) or await db["users"].find_one({"user_id": _user_id(persona)})
    if existing is None:
        return None
    if existing.get("academy_id") is not None:
        require_demo(existing.get("academy_id"))
    foreign = await db["academy_memberships"].find_one(
        {"user_id": existing.get("user_id"), "academy_id": {"$ne": DEMO_ACADEMY_ID}}
    )
    if foreign is not None:
        require_demo(foreign.get("academy_id"))
    return existing


def _build(now: datetime, user_ids: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    """Every tenant-owned document, by collection. Dates follow ``now`` so a
    re-run keeps classes around today (past ~4 weeks, next ~4 weeks)."""
    today = now.astimezone(ZoneInfo(TZ)).date()
    period = today.strftime("%Y-%m")
    owner, coach, parent = user_ids["owner"], user_ids["coach"], user_ids["parent"]

    sessions: list[dict[str, Any]] = []
    occurrences: list[dict[str, Any]] = []
    for session_id, title, day, start, end, price in (
        ("demo_session_sat", "Junior Beginners", "Sat", "09:00", "10:00", 80),
        ("demo_session_wed", "Junior Skills Clinic (free)", "Wed", "17:30", "18:30", 0),
    ):
        template = {
            "name": title,
            "location": "Demo Sports Center, Court 1",
            "max_students": 12,
            "days_of_week": [day],
            "start_time": start,
            "end_time": end,
            "timezone": TZ,
            "start_date": (today - timedelta(days=35)).isoformat(),
            "end_date": (today + timedelta(days=180)).isoformat(),
            "skill_level": "Beginner",
            "age_group": "8-12",
            "monthly_price": price,
        }
        session = build_recurring_session_doc(
            template,
            session_id=session_id,
            coach_id=coach,
            amount_cents=price * 100,
            created_at=now,
        )
        session["academy_id"] = DEMO_ACADEMY_ID
        sessions.append(session)
        for row in build_session_occurrence_docs(
            session, window_start=today, days_back=28, days_forward=28
        ):
            row["status"] = "completed" if cast(datetime, row["start_at"]) < now else "scheduled"
            occurrences.append(row)

    students = [
        {
            "academy_id": DEMO_ACADEMY_ID,
            "student_id": student_id,
            "first_name": first,
            "last_name": "Demo",
            "full_name": f"{first} Demo",
            "dob": dob,
            "skill_level": "Beginner",
            "parent_id": parent,
            "parent_user_id": parent,
            "waiver_accepted": True,
            "waiver_date": now,
            "status": "active",
            "is_deleted": False,
            "created_at": now,
        }
        for student_id, first, dob in (
            ("demo_student_sam", "Sam", "2016-04-12"),
            ("demo_student_alex", "Alex", "2018-09-30"),
        )
    ]
    waiver_acceptances = [
        {
            "academy_id": DEMO_ACADEMY_ID,
            "acceptance_id": f"demo_waiver_acceptance_{s['student_id']}",
            "student_id": s["student_id"],
            "parent_id": parent,
            "parent_user_id": parent,
            "accepted_by_user_id": parent,
            "waiver_template_id": "demo_waiver_template",
            "waiver_version_id": "demo_waiver_template",
            "accepted_at": now,
        }
        for s in students
    ]
    enrollments = [
        {
            "academy_id": DEMO_ACADEMY_ID,
            "enrollment_id": enrollment_id,
            "session_id": session_id,
            "student_id": student_id,
            "parent_id": parent,
            "parent_user_id": parent,
            "billing_type": "Standard",
            "approval_status": "approved",
            "status": "active",
            "enrolled_at": now - timedelta(days=35),
            "is_deleted": False,
        }
        for enrollment_id, session_id, student_id in (
            ("demo_enrollment_sam_sat", "demo_session_sat", "demo_student_sam"),
            ("demo_enrollment_alex_sat", "demo_session_sat", "demo_student_alex"),
            ("demo_enrollment_sam_wed", "demo_session_wed", "demo_student_sam"),
        )
    ]

    statuses = ("present", "present", "late", "present", "absent")
    attendance: list[dict[str, Any]] = []
    for occurrence in occurrences:
        if occurrence["status"] != "completed":
            continue
        for enrollment in enrollments:
            if enrollment["session_id"] != occurrence["session_id"]:
                continue
            attendance.append(
                {
                    "academy_id": DEMO_ACADEMY_ID,
                    "attendance_id": f"demo_attendance_{len(attendance) + 1:03d}",
                    "occurrence_id": occurrence["occurrence_id"],
                    "session_id": occurrence["session_id"],
                    "student_id": enrollment["student_id"],
                    "marked_by": coach,
                    "marked_at": occurrence["end_at"],
                    "status": statuses[len(attendance) % len(statuses)],
                    "client_app_version": "demo-seed",
                    "entry_source": "enrollment",
                }
            )

    # This month's tuition for both children: Sam's paid at the desk in cash,
    # Alex's open and due in two weeks. Keyed (enrollment, period) like the
    # monthly run's own invoices, so that run skips them instead of billing twice.
    invoices: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []
    for seq, (key, enrollment_id, student_id, paid) in enumerate(
        (
            ("sam", "demo_enrollment_sam_sat", "demo_student_sam", True),
            ("alex", "demo_enrollment_alex_sat", "demo_student_alex", False),
        ),
        start=1,
    ):
        due = today.replace(day=1) + timedelta(days=9) if paid else today + timedelta(days=14)
        invoices.append(
            {
                "academy_id": DEMO_ACADEMY_ID,
                "invoice_id": f"demo_invoice_{key}",
                "invoice_number": format_invoice_number(
                    prefix="DEMO", yyyymm=period.replace("-", ""), seq=seq
                ),
                "parent_id": parent,
                "student_id": student_id,
                "enrollment_id": enrollment_id,
                "session_id": "demo_session_sat",
                "period": period,
                "status": "paid" if paid else "open",
                "subtotal_cents": 8000,
                "discount_cents": 0,
                "total_cents": 8000,
                "balance_due_cents": 0 if paid else 8000,
                "refunded_cents": 0,
                "currency": "usd",
                "due_date": datetime.combine(due, time.min, tzinfo=UTC),
                "delivery_status": "not_sent",
                "finalized_at": now,
                "version": 0,
                "created_at": now,
                "updated_at": now,
            }
        )
        lines.append(
            {
                "academy_id": DEMO_ACADEMY_ID,
                "line_id": f"demo_line_{key}",
                "invoice_id": f"demo_invoice_{key}",
                "line_type": "tuition",
                "description": f"Junior Beginners tuition {period}",
                "quantity": 1,
                "unit_amount_cents": 8000,
                "amount_cents": 8000,
                "source_type": "enrollment",
                "source_id": enrollment_id,
                "created_at": now,
            }
        )
    paid_at = now - timedelta(days=3)
    payments = [
        {
            "academy_id": DEMO_ACADEMY_ID,
            "payment_id": "demo_payment_sam",
            "parent_id": parent,
            "amount_cents": 8000,
            "unapplied_amount_cents": 0,
            "currency": "usd",
            "status": "succeeded",
            "refunded_cents": 0,
            "payment_method": "cash",
            "stripe_payment_intent_id": None,
            "paid_at": paid_at,
            "recorded_by": owner,
            "notes": "Paid at the front desk",
            "created_at": paid_at,
            "updated_at": paid_at,
        }
    ]
    allocations = [
        {
            "academy_id": DEMO_ACADEMY_ID,
            "allocation_id": "demo_allocation_sam",
            "payment_id": "demo_payment_sam",
            "invoice_id": "demo_invoice_sam",
            "amount_cents": 8000,
            "idempotency_key": "demo_allocation_sam",
            "created_at": paid_at,
        }
    ]

    memberships = [
        {
            "academy_id": DEMO_ACADEMY_ID,
            "membership_id": f"demo_membership_{persona}",
            "user_id": user_ids[persona],
            "roles": roles,
            "status": "active",
            "invited_by": owner,
            "invited_at": now,
            "accepted_at": now,
            "created_at": now,
            "updated_at": now,
        }
        for persona, (_, _, roles) in PERSONAS.items()
    ]

    return {
        "academy_settings": [
            {
                "academy_id": DEMO_ACADEMY_ID,
                "settings_id": "demo_settings",
                "display_name": NAME,
                "timezone": TZ,
                "manual_methods": ["cash", "check"],
                "created_at": now,
                "updated_at": now,
            }
        ],
        "academy_domains": [
            {
                "academy_id": DEMO_ACADEMY_ID,
                "domain": DOMAIN,
                "slug": SLUG,
                "status": "verified",
                "kind": "tenant_subdomain",
                "created_at": now,
            }
        ],
        "academy_memberships": memberships,
        "sessions": sessions,
        "session_occurrences": occurrences,
        "students": students,
        "waiver_acceptances": waiver_acceptances,
        "enrollments": enrollments,
        "attendance": attendance,
        "invoices": invoices,
        "invoice_lines": lines,
        "ledger_payments": payments,
        "payment_allocations": allocations,
    }


#: collection -> the field a document is keyed (and pruned) by inside the academy.
KEYS: dict[str, str] = {
    "academy_settings": "settings_id",
    "academy_domains": "domain",
    "academy_memberships": "user_id",
    "sessions": "session_id",
    "session_occurrences": "occurrence_id",
    "students": "student_id",
    "waiver_acceptances": "acceptance_id",
    "enrollments": "enrollment_id",
    "attendance": "attendance_id",
    "invoices": "invoice_id",
    "invoice_lines": "line_id",
    "ledger_payments": "payment_id",
    "payment_allocations": "allocation_id",
}


async def _sync(db: Any, name: str, docs: list[dict[str, Any]]) -> None:
    """Replace each seeded doc, then delete the demo academy's other docs here."""
    key = KEYS[name]
    for doc in docs:
        require_demo(doc.get("academy_id"))
    for doc in docs:
        await db[name].replace_one({"academy_id": DEMO_ACADEMY_ID, key: doc[key]}, doc, upsert=True)
    await db[name].delete_many(
        {"academy_id": DEMO_ACADEMY_ID, key: {"$nin": [doc[key] for doc in docs]}}
    )


async def _upsert_user(
    db: Any, existing: dict[str, Any] | None, persona: str, firebase_uid: str, now: datetime
) -> str:
    email, display_name, roles = PERSONAS[persona]
    user_id = str((existing or {}).get("user_id") or _user_id(persona))
    doc = {
        "user_id": user_id,
        "email": email,
        "normalized_email": email,
        "display_name": display_name,
        "name": display_name,
        "firebase_uid": firebase_uid,
        "global_status": "active",
        "status": "active",
        "is_active": True,
        "academy_id": DEMO_ACADEMY_ID,
        "role": roles[-1],
        "roles": roles,
        "stripe_customer_id": None,
        "updated_at": now,
    }
    require_demo(doc["academy_id"])
    await db["users"].update_one(
        {"_id": existing["_id"]} if existing else {"user_id": user_id},
        {"$set": doc, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    return user_id


async def _suppress(db: Any, email: str, now: datetime) -> None:
    if email not in DEMO_EMAILS:
        raise DemoScopeError(f"refusing to suppress non-demo address {email!r}")
    await db["email_suppressions"].update_one(
        {"email": email},
        {
            "$set": {
                "reason": "hard_bounce",
                "bounce_subtype": "demo_seed",
                "provider": "demo_seed",
                "last_seen_at": now,
                "active": True,
                "released_at": None,
                "released_by": None,
            },
            "$setOnInsert": {
                "suppression_id": f"demo_suppression_{email.split('@')[0]}",
                "email": email,
                "first_seen_at": now,
                "first_seen_academy_id": DEMO_ACADEMY_ID,
            },
        },
        upsert=True,
    )


async def seed(
    db: Any,
    *,
    apply: bool,
    password: str | None = None,
    ensure_login: EnsureLogin = firebase_ensure_login,
    now: datetime | None = None,
) -> dict[str, int]:
    """Plan (dry run) or write the demo academy. Returns doc counts by collection."""
    now = now or datetime.now(UTC)
    await _refuse_foreign_academy(db)
    existing = {
        persona: await _refuse_foreign_user(db, persona, email)
        for persona, (email, _, _) in PERSONAS.items()
    }
    plan_ids = {p: str((existing[p] or {}).get("user_id") or _user_id(p)) for p in PERSONAS}
    counts = {name: len(docs) for name, docs in _build(now, plan_ids).items()}
    counts |= {"users": len(PERSONAS), "email_suppressions": len(PERSONAS)}
    if not apply:
        print(f"DRY RUN: would seed {NAME} ({DEMO_ACADEMY_ID}) at {DOMAIN}")
        for name, count in counts.items():
            print(f"  {name}: {count}")
        print("Re-run with --apply to write.")
        return counts
    if not password:
        raise ValueError("a password is required with --apply")

    user_ids: dict[str, str] = {}
    for persona, (email, display_name, _) in PERSONAS.items():
        uid = ensure_login(email, password, display_name)
        user_ids[persona] = await _upsert_user(db, existing[persona], persona, uid, now)

    # The platform's own bootstrap writes the academy row, the owner's first
    # membership, the default waiver and the invoice prefix. It reuses the
    # owner users row just written (found by email); the ids below are what it
    # mints only when a record does not exist yet.
    minted = {
        "acad_": DEMO_ACADEMY_ID,
        "user_": user_ids["owner"],
        "membership_": "demo_membership_owner",
        "wt_": "demo_waiver_template",
    }
    result = await BootstrapAcademy(
        store=MongoTenantBootstrapStore(db),
        invoice_prefix_assigner=compose_invoice_prefix_assigner(db),
        id_factory=lambda prefix: minted[prefix],
    ).execute(
        BootstrapAcademyCommand(
            display_name=NAME,
            slug=SLUG,
            primary_domain=DOMAIN,
            owner_email=PERSONAS["owner"][0],
            owner_display_name=PERSONAS["owner"][1],
            timezone=TZ,
        )
    )
    require_demo(result.academy_id)
    await db["academies"].update_one(
        {"academy_id": DEMO_ACADEMY_ID},
        {
            "$set": {
                "display_name": NAME,
                "timezone": TZ,
                "status": "active",
                "contact_email": PERSONAS["owner"][0],
                "updated_at": now,
            }
        },
    )
    for name, docs in _build(now, user_ids).items():
        await _sync(db, name, docs)
    for email in sorted(DEMO_EMAILS):
        await _suppress(db, email, now)
    print(f"Seeded {NAME} ({DEMO_ACADEMY_ID}) at https://{DOMAIN}")
    for persona, (email, _, roles) in PERSONAS.items():
        print(f"  {persona}: {email} roles={roles}")
    return counts


def _read_password() -> str:
    password = os.environ.get("DEMO_PASSWORD") or getpass.getpass("Demo password (shared): ")
    if len(password) < 8:
        raise SystemExit("The demo password must be at least 8 characters.")
    return password


async def _main(apply: bool) -> None:
    mongo_url, db_name = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        raise SystemExit("MONGO_URL and DB_NAME must be set.")
    password = _read_password() if apply else None
    client: AsyncIOMotorClient[Any] = AsyncIOMotorClient(mongo_url)
    try:
        await seed(client[db_name], apply=apply, password=password)
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed or reset the Demo Academy.")
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    asyncio.run(_main(parser.parse_args().apply))


if __name__ == "__main__":
    main()
