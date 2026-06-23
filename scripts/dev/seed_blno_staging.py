#!/usr/bin/env python3
"""seed_blno_staging.py - Full BLNO Badminton Academy seed for local SaaS staging.

Creates all BLNO data in one shot:
  Academy       BLno Badminton Academy  blno-academy.localhost  America/Chicago
  Users         Admin + 2 coaches + 36 parent accounts (Firebase emulator auth)
  Students      46 students linked to parents
  Sessions      4 recurring weekly classes (Wed + Thu)
  Occurrences   Apr 1 - Jun 30 2026 (past = completed, future = scheduled)
  Enrollments   All active / hold students
  Attendance    All past occurrences (~88% present, coach + student)
  Coach rates   30% revenue-share on expected revenue
  Payments      April + May + June 2026 with Stripe test IDs
                  April  - all succeeded
                  May    - mix: most succeeded, some pending, one failed
                  June   - all pending (current month)
  Subscriptions Monthly subscription per paying family
  Webhooks      Sample stripe_webhook_events for dedup testing
  Platform role Admin is platform_admin
  Skill pathway 6-level badminton programme (via seed_badminton_pathway.py)
  Progress      First 20 active students placed at Level 1 with mixed skill statuses

Fully idempotent — safe to re-run.

Usage:
    backend/.venv/bin/python scripts/dev/seed_blno_staging.py

Override targets:
    SAAS_STAGING_MONGO_URL      default mongodb://127.0.0.1:27017
    SAAS_STAGING_DB_NAME        default academy_manager_saas_staging
    SAAS_STAGING_EMULATOR_URL   default http://127.0.0.1:9099
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from pymongo import MongoClient

# ── configuration ─────────────────────────────────────────────────────────────

MONGO_URL = os.environ.get("SAAS_STAGING_MONGO_URL", "mongodb://127.0.0.1:27017")
DB_NAME = os.environ.get("SAAS_STAGING_DB_NAME", "academy_manager_saas_staging")
EMULATOR_URL = os.environ.get("SAAS_STAGING_EMULATOR_URL", "http://127.0.0.1:9099")
PROJECT_ID = "academy-courtmastr"
EMULATOR_API_KEY = f"emu-{PROJECT_ID}"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_DIR = PROJECT_ROOT / ".local"
CREDS_FILE = LOCAL_DIR / "saas-staging-credentials.json"
PATHWAY_SCRIPT = PROJECT_ROOT / "scripts" / "dev" / "seed_badminton_pathway.py"
VENV_PYTHON = os.environ.get(
    "VENV_PYTHON", str(PROJECT_ROOT / "backend" / ".venv" / "bin" / "python")
)
sys.path.insert(0, str(PROJECT_ROOT))

from backend.scripts.backfill_p4_legacy_payments import map_legacy_payment  # noqa: E402

ACADEMY_ID = "blno"
ACADEMY_SLUG = "blno"
ACADEMY_DOMAIN = "blno-academy.localhost"
ACADEMY_DISPLAY_NAME = "BLno Badminton Academy"
ACADEMY_TZ = "America/Chicago"
CHICAGO = ZoneInfo(ACADEMY_TZ)

ADMIN_EMAIL = os.environ.get("SAAS_STAGING_OWNER_EMAIL", "ramchand4685@gmail.com")
ADMIN_NAME = "RamC Venkatasamy"
ADMIN_PASSWORD = "Admin@12345"
COACH_PASSWORD = "Coach@12345"
PARENT_PASSWORD = "Parent@12345"

# Season date range for occurrences
SEASON_START = dt.date(2026, 4, 1)
SEASON_END = dt.date(2026, 6, 30)
TODAY = dt.date(2026, 6, 16)  # splits past (completed) from future (scheduled)


# ── safety guard ──────────────────────────────────────────────────────────────


def _assert_local() -> None:
    import urllib.parse as _up

    allowed = {"127.0.0.1", "localhost", "::1", "mongo", "firebase-emulator"}
    for label, url in (("mongo", MONGO_URL), ("emulator", EMULATOR_URL)):
        host = (_up.urlparse(url).hostname or "").lower()
        if host not in allowed:
            raise SystemExit(
                f"REFUSING: {label} host={host!r} is not local. "
                "This script seeds emulator-only test data and must not touch real infra."
            )


# ── datetime helpers ──────────────────────────────────────────────────────────


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def chicago_to_utc(date: dt.date, time_str: str) -> dt.datetime:
    h, m = (int(x) for x in time_str.split(":"))
    local = dt.datetime(date.year, date.month, date.day, h, m, tzinfo=CHICAGO)
    return local.astimezone(dt.UTC)


def all_weekdays(start: dt.date, end: dt.date, weekday: int) -> list[dt.date]:
    """Return every date in [start, end] matching Python weekday (2=Wed, 3=Thu)."""
    result, cur = [], start
    while cur <= end:
        if cur.weekday() == weekday:
            result.append(cur)
        cur += dt.timedelta(days=1)
    return result


# ── Firebase helpers ──────────────────────────────────────────────────────────


def _wait_for_services(client: Any) -> None:
    print("[blno-seed] Waiting for Firebase emulator...", file=sys.stderr)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{EMULATOR_URL}/", timeout=2.0)
            if r.status_code < 500:
                break
        except (httpx.HTTPError, OSError):
            pass
        time.sleep(1)
    else:
        raise RuntimeError("Firebase emulator not ready after 60s")

    print("[blno-seed] Waiting for Mongo...", file=sys.stderr)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            client.admin.command("ping")
            return
        except Exception:
            time.sleep(1)
    raise RuntimeError("Mongo not ready after 30s")


def _firebase_signup(email: str, password: str, display_name: str) -> str | None:
    r = httpx.post(
        f"{EMULATOR_URL}/identitytoolkit.googleapis.com/v1/accounts:signUp"
        f"?key={EMULATOR_API_KEY}",
        json={
            "email": email,
            "password": password,
            "displayName": display_name,
            "returnSecureToken": True,
        },
        timeout=5.0,
    )
    if r.status_code == 200:
        return str(r.json()["localId"])
    if "EMAIL_EXISTS" in r.text:
        return None
    raise RuntimeError(f"Firebase signup {email}: {r.status_code} {r.text[:200]}")


def _firebase_signin(email: str, password: str) -> str:
    r = httpx.post(
        f"{EMULATOR_URL}/identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
        f"?key={EMULATOR_API_KEY}",
        json={"email": email, "password": password, "returnSecureToken": True},
        timeout=5.0,
    )
    r.raise_for_status()
    return str(r.json()["localId"])


def upsert_firebase_user(email: str, password: str, display_name: str) -> str:
    uid = _firebase_signup(email, password, display_name)
    if uid is not None:
        _mark_firebase_email_verified(uid)
        return uid
    try:
        uid = _firebase_signin(email, password)
        _mark_firebase_email_verified(uid)
        return uid
    except Exception:
        # Password drift — clear account and recreate
        httpx.delete(
            f"{EMULATOR_URL}/emulator/v1/projects/{PROJECT_ID}/accounts",
            params={"email": email},
            timeout=5.0,
        )
        uid = _firebase_signup(email, password, display_name) or _firebase_signin(
            email, password
        )
        _mark_firebase_email_verified(uid)
        return uid


def _mark_firebase_email_verified(uid: str) -> None:
    """Mark an emulator Firebase user verified through the Admin SDK."""
    import urllib.parse as _urlparse

    import firebase_admin
    from firebase_admin import auth

    parsed = _urlparse.urlparse(EMULATOR_URL)
    emulator_host = parsed.netloc or parsed.path
    if not emulator_host:
        raise RuntimeError(f"Invalid Firebase emulator URL: {EMULATOR_URL}")

    previous_host = os.environ.get("FIREBASE_AUTH_EMULATOR_HOST")
    os.environ["FIREBASE_AUTH_EMULATOR_HOST"] = emulator_host
    app_name = f"blno-staging-seed-{PROJECT_ID}"
    try:
        try:
            app = firebase_admin.get_app(app_name)
        except ValueError:
            app = firebase_admin.initialize_app(
                options={"projectId": PROJECT_ID},
                name=app_name,
            )
        auth.update_user(uid, email_verified=True, app=app)
    finally:
        if previous_host is None:
            os.environ.pop("FIREBASE_AUTH_EMULATOR_HOST", None)
        else:
            os.environ["FIREBASE_AUTH_EMULATOR_HOST"] = previous_host


def mint_id_token(email: str, password: str) -> str:
    r = httpx.post(
        f"{EMULATOR_URL}/identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
        f"?key={EMULATOR_API_KEY}",
        json={"email": email, "password": password, "returnSecureToken": True},
        timeout=5.0,
    )
    r.raise_for_status()
    return str(r.json()["idToken"])


# ── data constants ────────────────────────────────────────────────────────────

SESSIONS_DEF: list[dict[str, Any]] = [
    {
        "key": "thu_beginner",
        "title": "Thursday 6:00 PM - 6:45 PM Beginner (Coach - Gowtham)",
        "coach_email": "gowtham@blno.academy",
        "weekday": 3,  # Thursday
        "start_time": "18:00",
        "end_time": "18:45",
        "skill_level": "beginner",
        "amount_cents": 6000,
        "capacity": 15,
    },
    {
        "key": "wed_intermediate",
        "title": "Wednesday 6:15 PM - 7:00 PM Intermediate (Coach - Kishore)",
        "coach_email": "kishore@blno.academy",
        "weekday": 2,  # Wednesday
        "start_time": "18:15",
        "end_time": "19:00",
        "skill_level": "intermediate",
        "amount_cents": 7000,
        "capacity": 15,
    },
    {
        "key": "thu_intermediate",
        "title": "Thursday 6:45 PM - 7:30 PM Intermediate (Coach - Gowtham)",
        "coach_email": "gowtham@blno.academy",
        "weekday": 3,  # Thursday
        "start_time": "18:45",
        "end_time": "19:30",
        "skill_level": "intermediate",
        "amount_cents": 7000,
        "capacity": 15,
    },
    {
        "key": "wed_beginner",
        "title": "Wednesday 5:45 PM - 6:30 PM Beginner (Coach - Kishore)",
        "coach_email": "kishore@blno.academy",
        "weekday": 2,  # Wednesday
        "start_time": "17:45",
        "end_time": "18:30",
        "skill_level": "beginner",
        "amount_cents": 6000,
        "capacity": 15,
    },
]

# Columns: student_name, parent_name, parent_email, phone, age, skill_level,
#          session_key, billing, status, apr_paid_cents, may_paid_cents
# billing : "standard" | "nocharge"
# status  : "active" | "hold" | "dropped"
# *_paid  : None = not paid / not applicable
ROSTER: list[tuple[Any, ...]] = [
    (
        "Nigazhini Manoj",
        "Manoj Edward",
        "manojedward.btech@gmail.com",
        "3095308920",
        6,
        "beginner",
        "thu_beginner",
        "standard",
        "active",
        6000,
        6000,
    ),
    (
        "Athiksha Sakthivel",
        "Sakthivel Shanmugam",
        "sakthivelplan@gmail.com",
        "3095326987",
        9,
        "beginner",
        "wed_intermediate",
        "standard",
        "active",
        7000,
        7000,
    ),
    (
        "Arjun V",
        "Viswanathan N",
        "viswanathan.kn@gmail.com",
        "3097507837",
        12,
        "intermediate",
        "wed_intermediate",
        "standard",
        "active",
        7000,
        7000,
    ),
    (
        "Surya Balakrishnan",
        "Krishna Balakrishnan",
        "krishnaswamib@gmail.com",
        "2487033410",
        12,
        "intermediate",
        "thu_intermediate",
        "standard",
        "active",
        7000,
        7000,
    ),
    (
        "Harshith Bhaskar",
        "Mohana Anandhan",
        "monaa1384@gmail.com",
        "3093100227",
        13,
        "beginner",
        "thu_intermediate",
        "standard",
        "active",
        7000,
        7000,
    ),
    (
        "Pradhyun Bhaskar",
        "Mohana Anandhan",
        "monaa1384@gmail.com",
        "3093100227",
        10,
        "beginner",
        "thu_intermediate",
        "standard",
        "active",
        7000,
        None,
    ),
    (
        "Netra Murugesan Ramya",
        "Murugesan Kollanur Palaniappan",
        "kpmpalaniappan@gmail.com",
        "3095315676",
        7,
        "beginner",
        "wed_beginner",
        "standard",
        "active",
        6000,
        6000,
    ),
    (
        "Hannah Sahaya Vinodh",
        "Sahaya Vinodh",
        "sahayavinodh@gmail.com",
        "3098077373",
        11,
        "intermediate",
        "wed_intermediate",
        "standard",
        "hold",
        7000,
        None,
    ),
    (
        "Vrushali Kariveda",
        "Rohith Kariveda",
        "rohith.myway@gmail.com",
        "8722029449",
        6,
        "beginner",
        "thu_beginner",
        "standard",
        "active",
        6000,
        6000,
    ),
    (
        "Varshali Kariveda",
        "Rohith Kariveda",
        "rohith.myway@gmail.com",
        "8722029449",
        6,
        "beginner",
        "thu_beginner",
        "standard",
        "active",
        6000,
        6000,
    ),
    (
        "Sadhvi Amireddy",
        "Uvaraju Amireddy",
        "uvaraju.a@gmail.com",
        "3095314079",
        11,
        "beginner",
        "wed_intermediate",
        "standard",
        "active",
        7000,
        7000,
    ),
    (
        "Jaanvi",
        "Raja Kakani",
        "rkakani8j378b@gmail.com",
        "7323575966",
        11,
        "beginner",
        "thu_intermediate",
        "standard",
        "active",
        7000,
        7000,
    ),
    (
        "Adhvik Saran",
        "Saran Maharajan",
        "saran.7176@gmail.com",
        "3093070358",
        8,
        "beginner",
        "thu_intermediate",
        "standard",
        "active",
        7000,
        None,
    ),
    (
        "Jayaparthiban Jawaharbabu",
        "Jawaharbabu Jeyaraman",
        "jawaharbabuj@gmail.com",
        "3098254798",
        6,
        "beginner",
        "wed_beginner",
        "standard",
        "active",
        6000,
        6000,
    ),
    (
        "Benjamin D'Mello",
        "Annalyn D'Mello",
        "annalynvaz@hotmail.com",
        "2242349703",
        12,
        "beginner",
        "wed_intermediate",
        "standard",
        "active",
        7000,
        7000,
    ),
    (
        "Jia Vidharthi Manoj Kumar",
        "Manoj Kumar M S",
        "msmanojreg@gmail.com",
        "3096125381",
        12,
        "intermediate",
        "wed_intermediate",
        "standard",
        "active",
        7000,
        7000,
    ),
    (
        "Sakshi Kishore",
        "Kishore Subbarao",
        "kishoreraosubbarao@gmail.com",
        "3095318717",
        11,
        "beginner",
        "thu_intermediate",
        "nocharge",
        "active",
        None,
        None,
    ),
    (
        "Vehith Kishore",
        "Kishore Subbarao",
        "kishoreraosubbarao@gmail.com",
        "3095318717",
        7,
        "beginner",
        "wed_intermediate",
        "nocharge",
        "active",
        None,
        None,
    ),
    (
        "Akshaya Senthilkumar",
        "Senthilkumar Mohan Raj",
        "msenthilvpm@gmail.com",
        "3098319331",
        10,
        "beginner",
        "thu_beginner",
        "standard",
        "active",
        6000,
        6000,
    ),
    (
        "Viha Ramchand",
        "RamC Venkatasamy",
        "ramchand4685@gmail.com",
        "2488859243",
        10,
        "beginner",
        "wed_intermediate",
        "nocharge",
        "active",
        None,
        None,
    ),
    (
        "Nilan Swaminathan Devi",
        "Devi Kumar",
        "devikv.devi@gmail.com",
        "3092054252",
        6,
        "beginner",
        "wed_beginner",
        "standard",
        "active",
        6000,
        6000,
    ),
    (
        "Aryan LK",
        "Kumaran Thirunavukkarasu",
        "kumar.thirunavukarasu1@gmail.com",
        "3095315600",
        7,
        "beginner",
        "wed_beginner",
        "standard",
        "active",
        6000,
        6000,
    ),
    (
        "Rihanth Sureshbabu",
        "Sureshbabu Dhandapani",
        "sureshbabu.dhandapani16@gmail.com",
        "3097509549",
        8,
        "intermediate",
        "wed_intermediate",
        "standard",
        "active",
        7000,
        7000,
    ),
    (
        "Suhaas Velaga",
        "Shravan Velaga",
        "velaga.shravan@gmail.com",
        "4255034059",
        6,
        "beginner",
        "thu_beginner",
        "standard",
        "active",
        6000,
        6000,
    ),
    (
        "Aishani Tummala",
        "Sri Tummala",
        "vasu.0145@gmail.com",
        "2488859206",
        6,
        "beginner",
        "wed_beginner",
        "standard",
        "dropped",
        6000,
        None,
    ),
    (
        "Anjana Sana",
        "Adi Sekhara Reddy Sana",
        "adisekharreddy@gmail.com",
        "5756391240",
        9,
        "beginner",
        "wed_beginner",
        "standard",
        "active",
        6000,
        6000,
    ),
    (
        "Abhishta Boddapati",
        "Prashanth Boddapati",
        "prasanthboddapati0805@gmail.com",
        "3095335123",
        10,
        "beginner",
        "wed_beginner",
        "standard",
        "active",
        6000,
        6000,
    ),
    (
        "Titiksha Vinothini Nirmalraj",
        "Nirmalraj",
        "nirmal16a@gmail.com",
        "3095315537",
        10,
        "beginner",
        "thu_intermediate",
        "standard",
        "active",
        7000,
        7000,
    ),
    (
        "Shamshritha Shivanuri",
        "Prem Kumar Shivanuri",
        "shivanuriprem@gmail.com",
        "3092629464",
        6,
        "beginner",
        "thu_beginner",
        "standard",
        "dropped",
        6000,
        None,
    ),
    (
        "Prisha",
        "Srinivasa Ramanujan",
        "sudharsan1987@gmail.com",
        "3092054741",
        6,
        "beginner",
        "wed_beginner",
        "standard",
        "active",
        6000,
        None,
    ),
    (
        "Kabilan Chandran",
        "Jayachandran Mallika Ramachandran",
        "m.r.jayachandran@gmail.com",
        "5623666960",
        14,
        "intermediate",
        "thu_intermediate",
        "standard",
        "active",
        7000,
        7000,
    ),
    (
        "Ethan Victor",
        "Victor Rajan",
        "mail2victors@gmail.com",
        "3093972925",
        14,
        "intermediate",
        "thu_intermediate",
        "standard",
        "active",
        7000,
        7000,
    ),
    (
        "Diya Saggu",
        "Anil Saggu",
        "sr_anilkumar@yahoo.com",
        "6307305638",
        8,
        "beginner",
        "wed_beginner",
        "standard",
        "active",
        6000,
        6000,
    ),
    (
        "Shakshitha Selvakumar",
        "Selvakumar Ramaiyah",
        "rselvakumarrsk@gmail.com",
        "3095300305",
        10,
        "intermediate",
        "thu_intermediate",
        "standard",
        "active",
        7000,
        7000,
    ),
    (
        "Yantraa Santosh",
        "Santosh Subramanian",
        "san6031@gmail.com",
        "3095324552",
        7,
        "beginner",
        "thu_beginner",
        "standard",
        "active",
        6000,
        6000,
    ),
    (
        "Vishwesh Srikanth",
        "Srikanth Marikkannu",
        "srimarikk@gmail.com",
        "3096602532",
        15,
        "intermediate",
        "thu_intermediate",
        "standard",
        "active",
        7000,
        7000,
    ),
    (
        "Ananyhaa Sudhakar",
        "Sudhakar Panneerselvam",
        "f1sudhakar@gmail.com",
        "2012388279",
        13,
        "beginner",
        "thu_beginner",
        "standard",
        "active",
        6000,
        7000,
    ),
    (
        "Maithri Kandula",
        "Mahesh Kandula",
        "mahesh.kandula34@gmail.com",
        "5713635113",
        6,
        "beginner",
        "thu_beginner",
        "standard",
        "active",
        6000,
        6000,
    ),
    (
        "Harini Manikandan",
        "Mohana Divya Lalitha Gunasekaran",
        "mohanadivya15@gmail.com",
        "3095855661",
        14,
        "beginner",
        "wed_intermediate",
        "standard",
        "active",
        7000,
        7000,
    ),
    (
        "Pooja Naran",
        "Maran Mani",
        "maran27.mani@gmail.com",
        "3094344206",
        11,
        "beginner",
        "wed_intermediate",
        "standard",
        "active",
        7000,
        7000,
    ),
    (
        "Divina",
        "David Jacob",
        "davidgentleguy@gmail.com",
        "3097504827",
        13,
        "intermediate",
        "wed_intermediate",
        "standard",
        "active",
        7000,
        7000,
    ),
    (
        "Radhesh Saravanan",
        "Saravanan Ramakrishnan",
        "saravananoff@hotmail.com",
        "3095320232",
        12,
        "beginner",
        "thu_beginner",
        "standard",
        "active",
        6000,
        6000,
    ),
    (
        "Dhanesh Saravanan",
        "Saravanan Ramakrishnan",
        "saravananoff@hotmail.com",
        "3095320232",
        10,
        "beginner",
        "thu_beginner",
        "standard",
        "active",
        6000,
        None,
    ),
    (
        "Aadhya Abhishek",
        "Abhishek Ajithkumar",
        "abhishekak.off@gmail.com",
        "3095315171",
        7,
        "beginner",
        "wed_beginner",
        "standard",
        "active",
        6000,
        6000,
    ),
    (
        "Kavishayashree Senthilkumar",
        "Senthilkumar Krishnan",
        "spsfamily7428@gmail.com",
        "3096848687",
        7,
        "beginner",
        "wed_beginner",
        "standard",
        "active",
        6000,
        6000,
    ),
    (
        "Riaan Pitale",
        "Rashmi Pitale",
        "rashmi.luniya@gmail.com",
        "3095313691",
        8,
        "beginner",
        "thu_beginner",
        "standard",
        "active",
        6000,
        6000,
    ),
]


# ── ID generators ─────────────────────────────────────────────────────────────


def _slug(text: str, max_len: int = 24) -> str:
    return (
        text.lower()
        .replace(" ", "_")
        .replace("'", "")
        .replace("@", "_at_")
        .replace(".", "_")[:max_len]
    )


def ses_id(key: str) -> str:
    return f"ses_blno_{key}"


def occ_id(key: str, date: dt.date) -> str:
    return f"occ_blno_{key}_{date.isoformat()}"


def std_id(name: str, idx: int) -> str:
    return f"std_blno_{idx:03d}_{_slug(name, 18)}"


def enr_id(student_id: str, session_key: str) -> str:
    return f"enr_{student_id[:20]}_{session_key}"


def mem_id(uid: str, role: str) -> str:
    return f"mem_{uid[:20]}_{role}"


def pay_id(parent_slug: str, month: str) -> str:
    return f"pay_blno_{parent_slug}_{month}"


def sub_doc_id(parent_slug: str) -> str:
    return f"sub_blno_{parent_slug}"


def stripe_cus(n: int) -> str:
    return f"cus_blno_test_{n:04d}"


def stripe_pi(n: int) -> str:
    return f"pi_blno_test_{n:04d}"


def stripe_cs(n: int) -> str:
    return f"cs_blnotest_{n:04d}"


def stripe_sub(n: int) -> str:
    return f"sub_blno_test_{n:04d}"


def stripe_evt(n: int, kind: str) -> str:
    return f"evt_blno_{kind.replace('.', '_')}_{n:04d}"


def build_student_tuition_payment_doc(
    *,
    payment_id: str,
    parent_id: str,
    student_id: str,
    enrollment_id: str,
    period: str,
    amount_cents: int,
    status: str,
    created_at: dt.datetime,
    updated_at: dt.datetime,
    stripe_payment_intent_id: str | None,
    stripe_checkout_session_id: str | None,
    description: str,
) -> dict[str, Any]:
    return {
        "payment_id": payment_id,
        "academy_id": ACADEMY_ID,
        "parent_id": parent_id,
        "student_id": student_id,
        "enrollment_id": enrollment_id,
        "period": period,
        "created_at": created_at,
        "updated_at": updated_at,
        "amount_cents": amount_cents,
        "currency": "usd",
        "status": status,
        "refunded_cents": 0,
        "stripe_payment_intent_id": stripe_payment_intent_id,
        "stripe_checkout_session_id": stripe_checkout_session_id,
        "billing_month": period,
        "payment_mode": "monthly",
        "description": description,
    }


def reset_blno_seed_billing_collections(db: Any) -> None:
    """Clear generated BLNO billing docs that are rebuilt with deterministic IDs."""
    db.payments.delete_many({"academy_id": ACADEMY_ID})
    db.parent_billing_customers.delete_many({"academy_id": ACADEMY_ID})
    # Local staging should audit the freshly seeded state, not stale terminal
    # queue rows left by earlier smoke runs.
    db.dead_letter_events.delete_many({})
    db.outbox_events.delete_many({})


def _upsert_ledger_from_seed_payment(db: Any, payment_doc: dict[str, Any]) -> None:
    mapped = map_legacy_payment(payment_doc)
    if mapped is None:
        return

    invoice = mapped["invoice"]
    line = mapped["line"]
    ledger_payment = mapped["ledger_payment"]
    allocation = mapped["allocation"]

    db.invoices.update_one(
        {"academy_id": invoice["academy_id"], "invoice_id": invoice["invoice_id"]},
        {"$set": invoice},
        upsert=True,
    )
    db.invoice_lines.update_one(
        {"academy_id": line["academy_id"], "line_id": line["line_id"]},
        {"$set": line},
        upsert=True,
    )
    if ledger_payment:
        db.ledger_payments.update_one(
            {
                "academy_id": ledger_payment["academy_id"],
                "payment_id": ledger_payment["payment_id"],
            },
            {"$set": ledger_payment},
            upsert=True,
        )
    if allocation:
        db.payment_allocations.update_one(
            {
                "academy_id": allocation["academy_id"],
                "allocation_id": allocation["allocation_id"],
            },
            {"$set": allocation},
            upsert=True,
        )


# ── main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    _assert_local()

    client: Any = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5_000)
    _wait_for_services(client)
    db = client[DB_NAME]
    ts = utcnow()
    reset_blno_seed_billing_collections(db)

    # ── 1. Firebase emulator accounts ─────────────────────────────────────────
    print("\n[blno-seed] 1/9  Firebase accounts...", file=sys.stderr)

    admin_uid = upsert_firebase_user(ADMIN_EMAIL, ADMIN_PASSWORD, ADMIN_NAME)
    gowtham_uid = upsert_firebase_user(
        "gowtham@blno.academy", COACH_PASSWORD, "Gowtham"
    )
    kishore_uid = upsert_firebase_user(
        "kishore@blno.academy", COACH_PASSWORD, "Kishore Subbarao"
    )
    print(f"  admin   {ADMIN_EMAIL} -> {admin_uid}", file=sys.stderr)
    print(f"  coach   gowtham@blno.academy -> {gowtham_uid}", file=sys.stderr)
    print(f"  coach   kishore@blno.academy -> {kishore_uid}", file=sys.stderr)

    # Collect unique parents; assign sequential Stripe customer indices
    parent_meta: dict[str, dict[str, Any]] = {}
    stripe_idx = 1
    for row in ROSTER:
        _, parent_name, parent_email, phone, *_ = row
        if parent_email not in parent_meta:
            # Pre-resolve UIDs for special accounts
            pre_uid: str | None = None
            if parent_email == ADMIN_EMAIL:
                pre_uid = admin_uid
            elif parent_email == "kishoreraosubbarao@gmail.com":
                pre_uid = kishore_uid
            parent_meta[parent_email] = {
                "name": parent_name,
                "phone": phone,
                "uid": pre_uid,
                "stripe_idx": stripe_idx,
            }
            stripe_idx += 1

    for email, meta in parent_meta.items():
        if meta["uid"] is None:
            meta["uid"] = upsert_firebase_user(email, PARENT_PASSWORD, meta["name"])

    coach_uid_map = {
        "gowtham@blno.academy": gowtham_uid,
        "kishore@blno.academy": kishore_uid,
    }
    print(f"  {len(parent_meta)} parent accounts created/verified", file=sys.stderr)

    # ── 2. Academy + settings ─────────────────────────────────────────────────
    print("[blno-seed] 2/9  Academy...", file=sys.stderr)
    db.academies.find_one_and_update(
        {"slug": ACADEMY_SLUG},
        {
            "$setOnInsert": {
                "slug": ACADEMY_SLUG,
                "created_at": ts,
            },
            "$set": {
                # academy_id forced here (not $setOnInsert) so a pre-existing
                # slug=blno doc from an earlier seed gets realigned to ACADEMY_ID.
                # All other collections key on this value — a mismatch 401s login.
                "academy_id": ACADEMY_ID,
                "display_name": ACADEMY_DISPLAY_NAME,
                "timezone": ACADEMY_TZ,
                "status": "active",
                "owner_email": ADMIN_EMAIL,
                "updated_at": ts,
                "primary_domain": ACADEMY_DOMAIN,
                "fees": {
                    "default_monthly_cents": 6000,
                    "late_fee_cents": 500,
                    "grace_days": 5,
                },
                "manual_methods": ["cash", "check", "zelle"],
                "notifications": {
                    "dues_reminders": True,
                    "attendance_alerts": True,
                    "daily_digest_to_admin": True,
                    "coach_digest_enabled": True,
                    "coach_digest_hour": 18,
                },
            },
        },
        upsert=True,
    )
    db.academy_settings.find_one_and_update(
        {"academy_id": ACADEMY_ID},
        {
            "$setOnInsert": {
                "settings_id": f"set_{ACADEMY_ID}",
                "academy_id": ACADEMY_ID,
                "display_name": ACADEMY_DISPLAY_NAME,
                "timezone": ACADEMY_TZ,
                "locale": "en-US",
                "created_at": ts,
            },
            "$set": {"updated_at": ts},
        },
        upsert=True,
    )

    # ── 3. Users + memberships ────────────────────────────────────────────────
    print("[blno-seed] 3/9  Users + memberships...", file=sys.stderr)

    def _upsert_user(
        uid: str, email: str, name: str, phone: str | None, roles: list[str]
    ) -> None:
        db.users.find_one_and_update(
            {"email": email},
            {
                "$setOnInsert": {"created_at": ts},
                "$set": {
                    "updated_at": ts,
                    "user_id": uid,
                    "firebase_uid": uid,
                    "auth_uid": uid,
                    "auth_provider": "firebase",
                    "email": email,
                    "normalized_email": email.lower().strip(),
                    "display_name": name,
                    "phone": phone,
                    "global_status": "active",
                    "is_active": True,
                    "roles": roles,
                    "role": roles[0],
                    "academy_id": ACADEMY_ID,
                },
            },
            upsert=True,
        )

    def _upsert_membership(uid: str, roles: list[str], status: str = "active") -> None:
        db.academy_memberships.find_one_and_update(
            {"academy_id": ACADEMY_ID, "user_id": uid},
            {
                "$setOnInsert": {
                    "membership_id": mem_id(uid, roles[0]),
                    "academy_id": ACADEMY_ID,
                    "user_id": uid,
                    "invited_by": admin_uid,
                    "invited_at": ts,
                    "accepted_at": ts,
                    "created_at": ts,
                },
                "$set": {"updated_at": ts, "roles": roles, "status": status},
            },
            upsert=True,
        )

    # Admin
    _upsert_user(admin_uid, ADMIN_EMAIL, ADMIN_NAME, "2488859243", ["admin"])
    _upsert_membership(admin_uid, ["admin"])
    db.platform_roles.find_one_and_update(
        {"user_id": admin_uid, "role": "platform_admin"},
        {
            "$setOnInsert": {
                "platform_role_id": f"prole_{admin_uid[:12]}",
                "granted_at": ts,
                "created_at": ts,
            },
            "$set": {"updated_at": ts, "status": "active"},
        },
        upsert=True,
    )

    # Coaches
    _upsert_user(gowtham_uid, "gowtham@blno.academy", "Gowtham", None, ["coach"])
    _upsert_membership(gowtham_uid, ["coach"])
    _upsert_user(
        kishore_uid, "kishore@blno.academy", "Kishore Subbarao", "3095318717", ["coach"]
    )
    _upsert_membership(kishore_uid, ["coach", "parent"])  # Kishore is also a parent

    # Parents
    for email, meta in parent_meta.items():
        uid = meta["uid"]
        if uid == admin_uid:
            _upsert_membership(uid, ["admin", "parent"])
            continue
        if uid == kishore_uid:
            continue  # already handled above
        _upsert_user(uid, email, meta["name"], meta["phone"], ["parent"])
        _upsert_membership(uid, ["parent"])

    # ── 4. Sessions ───────────────────────────────────────────────────────────
    print("[blno-seed] 4/9  Sessions...", file=sys.stderr)
    for sdef in SESSIONS_DEF:
        sid = ses_id(sdef["key"])
        c_uid = coach_uid_map[sdef["coach_email"]]
        db.sessions.find_one_and_update(
            {"session_id": sid},
            {
                "$setOnInsert": {
                    "session_id": sid,
                    "academy_id": ACADEMY_ID,
                    "created_at": ts,
                },
                "$set": {
                    "updated_at": ts,
                    "title": sdef["title"],
                    "coach_id": c_uid,
                    "location": "BLNO Court 3",
                    "capacity": sdef["capacity"],
                    "amount_cents": sdef["amount_cents"],
                    "status": "scheduled",
                    "skill_level": sdef["skill_level"],
                    "age_group": "All",
                    "days_of_week": ["Wed" if sdef["weekday"] == 2 else "Thu"],
                    "start_time": sdef["start_time"],
                    "end_time": sdef["end_time"],
                    "timezone": ACADEMY_TZ,
                    "start_date": SEASON_START.isoformat(),
                    "end_date": SEASON_END.isoformat(),
                },
            },
            upsert=True,
        )

    # ── 5. Occurrences ────────────────────────────────────────────────────────
    print("[blno-seed] 5/9  Occurrences...", file=sys.stderr)
    occ_count = 0
    for sdef in SESSIONS_DEF:
        sid = ses_id(sdef["key"])
        c_uid = coach_uid_map[sdef["coach_email"]]
        for date in all_weekdays(SEASON_START, SEASON_END, sdef["weekday"]):
            oid = occ_id(sdef["key"], date)
            is_past = date < TODAY
            db.session_occurrences.find_one_and_update(
                {"occurrence_id": oid},
                {
                    "$setOnInsert": {
                        "occurrence_id": oid,
                        "session_id": sid,
                        "template_session_id": sid,
                        "academy_id": ACADEMY_ID,
                        "created_at": ts,
                    },
                    "$set": {
                        "updated_at": ts,
                        "start_at": chicago_to_utc(date, sdef["start_time"]),
                        "end_at": chicago_to_utc(date, sdef["end_time"]),
                        "status": "completed" if is_past else "scheduled",
                        "scheduled_coach_id": c_uid,
                        "actual_coach_id": c_uid if is_past else None,
                        "substitute_coach_id": None,
                        "is_billable": True,
                        "is_payable": True,
                        "cancellation_reason": None,
                    },
                },
                upsert=True,
            )
            occ_count += 1
    print(f"  {occ_count} occurrences", file=sys.stderr)

    # ── 6. Students + Enrollments ─────────────────────────────────────────────
    print("[blno-seed] 6/9  Students + enrollments...", file=sys.stderr)
    student_records: list[dict[str, Any]] = []
    enr_status_map = {"active": "active", "hold": "paused", "dropped": "withdrawn"}

    for i, row in enumerate(ROSTER):
        (
            student_name,
            _parent_name,
            parent_email,
            _phone,
            age,
            skill_level,
            session_key,
            billing,
            status,
            apr_paid,
            may_paid,
        ) = row

        p_uid = parent_meta[parent_email]["uid"]
        sid = std_id(student_name, i)
        s_id = ses_id(session_key)
        e_id = enr_id(sid, session_key)

        db.students.find_one_and_update(
            {"student_id": sid},
            {
                "$setOnInsert": {
                    "student_id": sid,
                    "academy_id": ACADEMY_ID,
                    "parent_id": p_uid,
                    "created_at": ts,
                },
                "$set": {
                    "updated_at": ts,
                    "full_name": student_name,
                    "date_of_birth": f"{2026 - age}-06-15",
                    "skill_level": skill_level,
                    "status": "inactive" if status == "dropped" else "active",
                },
            },
            upsert=True,
        )
        db.enrollments.find_one_and_update(
            {"enrollment_id": e_id},
            {
                "$setOnInsert": {
                    "enrollment_id": e_id,
                    "academy_id": ACADEMY_ID,
                    "session_id": s_id,
                    "student_id": sid,
                    "created_at": ts,
                },
                "$set": {
                    "updated_at": ts,
                    "status": enr_status_map[status],
                    "billing_type": billing,
                },
            },
            upsert=True,
        )
        student_records.append(
            {
                "student_id": sid,
                "student_name": student_name,
                "parent_email": parent_email,
                "parent_uid": p_uid,
                "session_key": session_key,
                "session_id": s_id,
                "enrollment_id": e_id,
                "billing": billing,
                "status": status,
                "apr_paid": apr_paid,
                "may_paid": may_paid,
            }
        )
    print(
        f"  {len(student_records)} students, {len(student_records)} enrollments",
        file=sys.stderr,
    )

    # ── 7. Payments + Subscriptions (Stripe test data) ────────────────────────
    print("[blno-seed] 7/9  Payments + Stripe...", file=sys.stderr)

    standard_student_records = [
        rec for rec in student_records if rec["billing"] == "standard"
    ]
    paying_parent_emails = sorted(
        {rec["parent_email"] for rec in standard_student_records}
    )
    pay_counter = 1
    for email in paying_parent_emails:
        meta = parent_meta[email]
        p_uid = meta["uid"]
        p_slug = _slug(email.split("@")[0], 24)
        s_idx = meta["stripe_idx"]
        cus_id = stripe_cus(s_idx)
        sub_s_id = stripe_sub(s_idx)

        db.parent_billing_customers.find_one_and_update(
            {"academy_id": ACADEMY_ID, "parent_id": p_uid},
            {
                "$setOnInsert": {
                    "academy_id": ACADEMY_ID,
                    "parent_id": p_uid,
                    "created_at": ts,
                },
                "$set": {
                    "stripe_customer_id": cus_id,
                    "updated_at": ts,
                },
            },
            upsert=True,
        )

        # Subscription record (one per paying family)
        db.subscriptions.find_one_and_update(
            {"subscription_id": sub_doc_id(p_slug)},
            {
                "$setOnInsert": {
                    "subscription_id": sub_doc_id(p_slug),
                    "academy_id": ACADEMY_ID,
                    "parent_id": p_uid,
                    "created_at": dt.datetime(2026, 4, 1, 0, 0, 0, tzinfo=dt.UTC),
                },
                "$set": {
                    "updated_at": ts,
                    "stripe_subscription_id": sub_s_id,
                    "processor_refs": {
                        "stripe_customer_id": cus_id,
                        "stripe_subscription_id": sub_s_id,
                    },
                    "status": "active",
                    "payment_mode": "monthly",
                },
            },
            upsert=True,
        )

    for rec in standard_student_records:
        email = rec["parent_email"]
        meta = parent_meta[email]
        p_uid = meta["uid"]
        p_slug = _slug(email.split("@")[0], 24)
        s_idx = meta["stripe_idx"]
        student_slug = _slug(rec["student_name"], 24)
        apr_paid = int(rec["apr_paid"] or 0)
        may_paid = int(rec["may_paid"] or 0)

        # April payment - all succeeded
        if apr_paid > 0:
            _upsert_ledger_from_seed_payment(
                db,
                build_student_tuition_payment_doc(
                    payment_id=pay_id(f"{p_slug}_{student_slug}", "apr2026"),
                    parent_id=p_uid,
                    student_id=rec["student_id"],
                    enrollment_id=rec["enrollment_id"],
                    period="2026-04",
                    created_at=dt.datetime(2026, 4, 1, 0, 0, 0, tzinfo=dt.UTC),
                    updated_at=dt.datetime(2026, 4, 5, 10, 0, 0, tzinfo=dt.UTC),
                    amount_cents=apr_paid,
                    status="succeeded",
                    stripe_payment_intent_id=stripe_pi(pay_counter),
                    stripe_checkout_session_id=stripe_cs(pay_counter),
                    description="April 2026 tuition",
                ),
            )
            pay_counter += 1

        # May payment - varied: succeeded / pending / failed
        if may_paid > 0:
            if s_idx % 10 == 7:
                may_status, may_pi = "failed", stripe_pi(pay_counter)
            elif s_idx % 5 == 0:
                may_status, may_pi = "pending", None
            else:
                may_status, may_pi = "succeeded", stripe_pi(pay_counter)

            _upsert_ledger_from_seed_payment(
                db,
                build_student_tuition_payment_doc(
                    payment_id=pay_id(f"{p_slug}_{student_slug}", "may2026"),
                    parent_id=p_uid,
                    student_id=rec["student_id"],
                    enrollment_id=rec["enrollment_id"],
                    period="2026-05",
                    created_at=dt.datetime(2026, 5, 1, 0, 0, 0, tzinfo=dt.UTC),
                    updated_at=dt.datetime(2026, 5, 5, 10, 0, 0, tzinfo=dt.UTC),
                    amount_cents=may_paid,
                    status=may_status,
                    stripe_payment_intent_id=may_pi,
                    stripe_checkout_session_id=stripe_cs(pay_counter),
                    description="May 2026 tuition",
                ),
            )
            pay_counter += 1

        # June payment - all pending (current month, not yet collected)
        june_amount = may_paid or apr_paid
        if june_amount:
            _upsert_ledger_from_seed_payment(
                db,
                build_student_tuition_payment_doc(
                    payment_id=pay_id(f"{p_slug}_{student_slug}", "jun2026"),
                    parent_id=p_uid,
                    student_id=rec["student_id"],
                    enrollment_id=rec["enrollment_id"],
                    period="2026-06",
                    created_at=dt.datetime(2026, 6, 1, 0, 0, 0, tzinfo=dt.UTC),
                    updated_at=dt.datetime(2026, 6, 1, 0, 0, 0, tzinfo=dt.UTC),
                    amount_cents=june_amount,
                    status="pending",
                    stripe_payment_intent_id=None,
                    stripe_checkout_session_id=None,
                    description="June 2026 tuition",
                ),
            )

    # Sample stripe_webhook_events for dedup/replay testing
    for evt_doc in [
        {
            "event_id": stripe_evt(1, "checkout.session.completed"),
            "event_type": "checkout.session.completed",
            "object_id": stripe_cs(1),
            "object_type": "checkout.session",
            "livemode": False,
            "status": "processed",
            "retry_count": 0,
            "academy_id": ACADEMY_ID,
            "received_at": dt.datetime(2026, 4, 5, 10, 0, 0, tzinfo=dt.UTC),
            "processed_at": dt.datetime(2026, 4, 5, 10, 0, 5, tzinfo=dt.UTC),
        },
        {
            "event_id": stripe_evt(2, "customer.subscription.updated"),
            "event_type": "customer.subscription.updated",
            "object_id": stripe_sub(1),
            "object_type": "subscription",
            "livemode": False,
            "status": "processed",
            "retry_count": 0,
            "academy_id": ACADEMY_ID,
            "received_at": dt.datetime(2026, 5, 1, 0, 0, 0, tzinfo=dt.UTC),
            "processed_at": dt.datetime(2026, 5, 1, 0, 0, 3, tzinfo=dt.UTC),
        },
        {
            "event_id": stripe_evt(3, "payment_intent.payment_failed"),
            "event_type": "payment_intent.payment_failed",
            "object_id": stripe_pi(7),
            "object_type": "payment_intent",
            "livemode": False,
            "status": "processed",
            "retry_count": 0,
            "academy_id": ACADEMY_ID,
            "received_at": dt.datetime(2026, 5, 5, 10, 15, 0, tzinfo=dt.UTC),
            "processed_at": dt.datetime(2026, 5, 5, 10, 15, 4, tzinfo=dt.UTC),
        },
        {
            "event_id": stripe_evt(4, "charge.refunded"),
            "event_type": "charge.refunded",
            "object_id": "ch_blno_test_0001",
            "object_type": "charge",
            "livemode": False,
            "status": "processed",
            "retry_count": 0,
            "academy_id": ACADEMY_ID,
            "received_at": dt.datetime(2026, 4, 10, 14, 0, 0, tzinfo=dt.UTC),
            "processed_at": dt.datetime(2026, 4, 10, 14, 0, 2, tzinfo=dt.UTC),
        },
    ]:
        db.stripe_webhook_events.find_one_and_update(
            {"event_id": evt_doc["event_id"]},
            {"$setOnInsert": {**evt_doc, "created_at": evt_doc["received_at"]}},
            upsert=True,
        )
    print(
        f"  ~{pay_counter - 1} invoice-ledger records + 4 webhook events seeded",
        file=sys.stderr,
    )

    # ── 8. Coach rates + attendance ───────────────────────────────────────────
    print("[blno-seed] 8/9  Coach rates + attendance...", file=sys.stderr)

    for _c_email, c_uid in coach_uid_map.items():
        db.coach_rates.find_one_and_update(
            {"coach_id": c_uid, "academy_id": ACADEMY_ID},
            {
                "$setOnInsert": {
                    "rate_id": f"rate_blno_{c_uid[:12]}",
                    "academy_id": ACADEMY_ID,
                    "coach_id": c_uid,
                    "created_at": ts,
                },
                "$set": {
                    "updated_at": ts,
                    "billing_unit": "percent_of_revenue",
                    "amount_minor": 0,
                    "percent_bps": 3000,
                    "currency": "USD",
                    "rate_type": "percentage_of_expected_revenue",
                    "percentage": 30.0,
                    "basis": "expected",
                    "per_session_cents": 2500,
                    "effective_from": dt.datetime(2026, 4, 1, 0, 0, 0, tzinfo=dt.UTC),
                    "status": "active",
                },
            },
            upsert=True,
        )

    # Build per-session enrolled-student lookup
    session_students: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in student_records:
        if rec["status"] in ("active", "hold"):
            session_students[rec["session_key"]].append(rec)

    att_count = 0
    for sdef in SESSIONS_DEF:
        c_uid = coach_uid_map[sdef["coach_email"]]
        enrolled = session_students[sdef["key"]]
        for date in all_weekdays(
            SEASON_START, TODAY - dt.timedelta(days=1), sdef["weekday"]
        ):
            oid = occ_id(sdef["key"], date)
            end_utc = chicago_to_utc(date, sdef["end_time"])

            # Coach always present in seed data
            db.coach_attendance.find_one_and_update(
                {"occurrence_id": oid, "coach_id": c_uid},
                {
                    "$setOnInsert": {
                        "attendance_id": f"ca_{oid[:40]}",
                        "academy_id": ACADEMY_ID,
                        "occurrence_id": oid,
                        "coach_id": c_uid,
                        "created_at": ts,
                    },
                    "$set": {
                        "status": "present",
                        "role": "lead",
                        "source": "admin",
                        "marked_by": admin_uid,
                        "marked_at": end_utc,
                    },
                },
                upsert=True,
            )

            # Students — ~88% present, hold students absent from May onward
            for si, rec in enumerate(enrolled):
                if rec["status"] == "hold" and date >= dt.date(2026, 5, 1):
                    continue
                att_status = "absent" if (si + date.day) % 9 == 0 else "present"
                db.attendance.find_one_and_update(
                    {"occurrence_id": oid, "student_id": rec["student_id"]},
                    {
                        "$setOnInsert": {
                            "attendance_id": f"att_{oid}_{rec['student_id']}",
                            "academy_id": ACADEMY_ID,
                            "occurrence_id": oid,
                            "session_id": rec["session_id"],
                            "student_id": rec["student_id"],
                            "date": dt.datetime(
                                date.year, date.month, date.day, tzinfo=dt.UTC
                            ),
                            "created_at": ts,
                        },
                        "$set": {
                            "status": att_status,
                            "marked_by": c_uid,
                            "marked_at": end_utc,
                        },
                    },
                    upsert=True,
                )
                att_count += 1

    print(f"  {att_count} student attendance records", file=sys.stderr)

    # ── 9. Skill pathway + student progress ───────────────────────────────────
    print("[blno-seed] 9/9  Skill pathway...", file=sys.stderr)
    program_id: str | None = None

    if PATHWAY_SCRIPT.exists():
        result = subprocess.run(
            [VENV_PYTHON, str(PATHWAY_SCRIPT)],
            cwd=str(PROJECT_ROOT),
            env={
                **os.environ,
                "MONGO_URL": MONGO_URL,
                "DB_NAME": DB_NAME,
                "ACADEMY_ID": ACADEMY_ID,
                "SEED_USER_ID": admin_uid,
                "PYTHONPATH": str(PROJECT_ROOT),
            },
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(
                f"  WARNING: pathway seed failed:\n{result.stderr[-500:]}",
                file=sys.stderr,
            )
        else:
            print("  Badminton pathway seeded OK", file=sys.stderr)
            try:
                program_id = json.loads(result.stdout).get("program_id")
            except (json.JSONDecodeError, AttributeError):
                pass
    else:
        print(f"  WARNING: {PATHWAY_SCRIPT} not found — skipping", file=sys.stderr)

    # Seed Level 1 progress for first 20 active students
    if program_id:
        level = db.skill_levels.find_one(
            {"academy_id": ACADEMY_ID, "program_id": program_id, "sequence": 1}
        )
        all_skills = list(
            db.skills.find({"academy_id": ACADEMY_ID, "program_id": program_id})
        )
        if level and all_skills:
            level_id = level["level_id"]
            level1_skills = [s for s in all_skills if s.get("level_id") == level_id]
            statuses = ["NOT_STARTED", "INTRODUCED", "LEARNING", "PRACTICING", "PASSED"]
            active_sample = [r for r in student_records if r["status"] == "active"][:20]

            for i, rec in enumerate(active_sample):
                sid = rec["student_id"]
                db.student_level_progress.find_one_and_update(
                    {
                        "academy_id": ACADEMY_ID,
                        "student_id": sid,
                        "program_id": program_id,
                        "level_id": level_id,
                    },
                    {
                        "$setOnInsert": {
                            "progress_id": f"lp_blno_{sid[:16]}",
                            "academy_id": ACADEMY_ID,
                            "student_id": sid,
                            "program_id": program_id,
                            "level_id": level_id,
                            "status": "active",
                            "started_at": dt.datetime(
                                2026, 4, 1, 0, 0, 0, tzinfo=dt.UTC
                            ),
                            "completed_at": None,
                            "created_at": ts,
                        },
                        "$set": {"updated_at": ts},
                    },
                    upsert=True,
                )
                for j, skill in enumerate(level1_skills):
                    skill_status = statuses[(i + j) % len(statuses)]
                    db.student_skill_progress.find_one_and_update(
                        {
                            "academy_id": ACADEMY_ID,
                            "student_id": sid,
                            "skill_id": skill["skill_id"],
                        },
                        {
                            "$setOnInsert": {
                                "skill_progress_id": f"sp_{sid[:12]}_{skill['skill_id'][:8]}",
                                "academy_id": ACADEMY_ID,
                                "student_id": sid,
                                "program_id": program_id,
                                "level_id": level_id,
                                "skill_id": skill["skill_id"],
                                "introduced_at": (
                                    dt.datetime(2026, 4, 5, 0, 0, 0, tzinfo=dt.UTC)
                                    if skill_status != "NOT_STARTED"
                                    else None
                                ),
                                "created_at": ts,
                            },
                            "$set": {
                                "status": skill_status,
                                "last_updated_at": ts,
                                "last_updated_by": gowtham_uid,
                            },
                        },
                        upsert=True,
                    )
            print(
                f"  Level 1 progress seeded for {len(active_sample)} students",
                file=sys.stderr,
            )

    # ── Write credentials file ────────────────────────────────────────────────
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    CREDS_FILE.write_text(
        json.dumps(
            {
                "owners": {
                    ADMIN_EMAIL: {
                        "owner_email": ADMIN_EMAIL,
                        "owner_password": ADMIN_PASSWORD,
                    }
                },
                "coaches": {
                    "gowtham@blno.academy": COACH_PASSWORD,
                    "kishore@blno.academy": COACH_PASSWORD,
                },
                "sample_parent": {
                    "email": "manojedward.btech@gmail.com",
                    "password": PARENT_PASSWORD,
                    "student": "Nigazhini Manoj",
                },
                "note": (
                    "Local Firebase Auth Emulator only. "
                    "Auto-generated by seed_blno_staging.py. Do not reuse."
                ),
            },
            indent=2,
        )
    )
    CREDS_FILE.chmod(0o600)

    result = subprocess.run(
        [
            VENV_PYTHON,
            "-c",
            (
                "import asyncio, os;"
                "from motor.motor_asyncio import AsyncIOMotorClient;"
                "from backend.v2.migrations.runner import run_all_migrations;"
                "\nasync def main():\n"
                "    client = AsyncIOMotorClient(os.environ['SAAS_STAGING_MONGO_URL'])\n"
                "    try:\n"
                "        replayed = await run_all_migrations(client[os.environ['SAAS_STAGING_DB_NAME']])\n"
                "        print(f'Replayed {len(replayed)} migrations')\n"
                "    finally:\n"
                "        client.close()\n"
                "asyncio.run(main())\n"
            ),
        ],
        cwd=str(PROJECT_ROOT),
        env={
            **os.environ,
            "PYTHONPATH": str(PROJECT_ROOT),
            "SAAS_STAGING_MONGO_URL": MONGO_URL,
            "SAAS_STAGING_DB_NAME": DB_NAME,
        },
        check=True,
    )
    print(f"  {result.stdout or 'Migrations replayed'}", file=sys.stderr)

    # ── Summary ───────────────────────────────────────────────────────────────
    admin_token = mint_id_token(ADMIN_EMAIL, ADMIN_PASSWORD)

    print("\n=== BLNO seed complete ===", file=sys.stderr)
    print(f"  Academy:        {ACADEMY_ID}  ({ACADEMY_DISPLAY_NAME})", file=sys.stderr)
    print(f"  Login URL:      http://{ACADEMY_DOMAIN}:3000/login", file=sys.stderr)
    print(f"  Admin:          {ADMIN_EMAIL}  /  {ADMIN_PASSWORD}", file=sys.stderr)
    print(
        f"  Coach Gowtham:  gowtham@blno.academy  /  {COACH_PASSWORD}", file=sys.stderr
    )
    print(
        f"  Coach Kishore:  kishore@blno.academy  /  {COACH_PASSWORD}", file=sys.stderr
    )
    print(
        f"  Parent (eg):    manojedward.btech@gmail.com  /  {PARENT_PASSWORD}",
        file=sys.stderr,
    )
    print(
        f"  Students:       {len(student_records)} across 4 sessions", file=sys.stderr
    )
    print(
        f"  Stripe test:    cus_blno_test_0001 … cus_blno_test_{len(parent_meta):04d}",
        file=sys.stderr,
    )
    print(f"  Creds file:     {CREDS_FILE}", file=sys.stderr)
    print(file=sys.stderr)
    print("  export API_URL='http://127.0.0.1:8001'", file=sys.stderr)
    print("  export FRONTEND_URL='http://localhost:3000'", file=sys.stderr)
    print(
        f"  export TENANT_FRONTEND_URL='http://{ACADEMY_DOMAIN}:3000'", file=sys.stderr
    )
    print(
        "  export INTERNAL_TENANT_HEADER_NAME='x-internal-tenant-id'", file=sys.stderr
    )
    print(f"  export INTERNAL_TENANT_HEADER_VALUE='{ACADEMY_ID}'", file=sys.stderr)
    print(f"  export AUTH_TOKEN='{admin_token}'", file=sys.stderr)


if __name__ == "__main__":
    main()
