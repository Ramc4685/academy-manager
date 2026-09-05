"""Standalone local seed for BLno Badminton Academy.

Drops all transactional collections, keeps only the configured admin user,
then re-seeds coaches, sessions, parents, students, enrollments, payments,
attendance, expenses and payout rules from the real Apr/May 2026 roster.

All documents are written in v2-compatible schema:
  - academy_id on every document
  - session_id / student_id / enrollment_id / payment_id / expense_id string keys
  - title / capacity / amount_cents on sessions
  - parent_id / full_name on students
  - status: "succeeded" on paid payments
  - categories matching v2 Literal on expenses

Run from repo root:
    source backend/.venv/bin/activate
    python3 backend/scripts/seed_local.py

Firebase emulator mode (requires emulator running on :9099):
    FIREBASE_AUTH_ENABLED=true python3 backend/scripts/seed_local.py

No Excel file required.
"""

import asyncio
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import UTC, date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import bcrypt
import firebase_admin
from firebase_admin import auth as firebase_admin_auth, credentials as firebase_admin_credentials
from motor.motor_asyncio import AsyncIOMotorClient
from backend.scripts.backfill_p4_legacy_payments import map_legacy_payment
from backend.v2.shared.ids import new_ulid


def _init_firebase_admin() -> None:
    if firebase_admin._apps:
        return
    options = {"projectId": FIREBASE_PROJECT}
    try:
        cred = firebase_admin_credentials.ApplicationDefault()
        firebase_admin.initialize_app(cred, options)
    except Exception:
        firebase_admin.initialize_app(options=options)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ADMIN_PASSWORD = os.environ.get("SEED_ADMIN_PASSWORD", "CHANGE_ME")
COACH_PASSWORD = os.environ.get("SEED_COACH_PASSWORD", "CHANGE_ME")
PARENT_PASSWORD = os.environ.get("SEED_PARENT_PASSWORD", "CHANGE_ME")
FIREBASE_MODE = os.environ.get("FIREBASE_AUTH_ENABLED", "").lower() in ("1", "true", "yes")
FIREBASE_PROJECT = os.environ.get("FIREBASE_PROJECT_ID", "academy-courtmastr")
FIREBASE_EMULATOR = os.environ.get("FIREBASE_AUTH_EMULATOR_HOST", "127.0.0.1:9099")
ACADEMY_ID = "blno"
ACADEMY_NAME = "BLno Badminton Academy"
ACADEMY_TZ = "America/Chicago"

# Day-of-week abbreviation → Python weekday() int.
DOW_MAP: dict[str, int] = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}


def expand_template_to_dated_sessions(
    template: dict,
    today: date,
    weeks_back: int = 4,
    weeks_forward: int = 12,
) -> list[tuple[datetime, datetime]]:
    """Expand a weekly recurring template into legacy dated session pairs."""
    dow_strs: list[str] = list(template.get("days_of_week") or [])
    dow_ints = {DOW_MAP[d] for d in dow_strs if d in DOW_MAP}
    if not dow_ints:
        return []
    sh, sm = int(template["start_time"][:2]), int(template["start_time"][3:5])
    eh, em = int(template["end_time"][:2]), int(template["end_time"][3:5])
    start = today - timedelta(weeks=weeks_back)
    end = today + timedelta(weeks=weeks_forward)
    dated: list[tuple[datetime, datetime]] = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() in dow_ints:
            dated.append(
                (
                    datetime.combine(cursor, time(sh, sm), tzinfo=timezone.utc),
                    datetime.combine(cursor, time(eh, em), tzinfo=timezone.utc),
                )
            )
        cursor += timedelta(days=1)
    return dated


def _template_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    return None


def _first_matching_template_date(template: dict[str, object], fallback: date) -> date:
    start_date = _template_date(template.get("start_date")) or fallback
    end_date = _template_date(template.get("end_date"))
    dow_ints = {
        DOW_MAP[str(day)[:3].title()]
        for day in list(template.get("days_of_week") or [])
        if str(day)[:3].title() in DOW_MAP
    }
    if not dow_ints:
        return start_date

    current = start_date
    while end_date is None or current <= end_date:
        if current.weekday() in dow_ints:
            return current
        current += timedelta(days=1)
    return start_date


def _local_datetime(
    local_date: date,
    value: object,
    timezone_name: str,
) -> datetime:
    parsed_time = time.fromisoformat(str(value))
    return datetime.combine(local_date, parsed_time, tzinfo=ZoneInfo(timezone_name)).astimezone(UTC)


def build_recurring_session_doc(
    template: dict[str, object],
    *,
    session_id: str,
    coach_id: str,
    amount_cents: int,
    created_at: datetime,
) -> dict[str, object]:
    """Build the canonical local seed session document for a weekly class."""
    timezone_name = str(template.get("timezone") or ACADEMY_TZ)
    representative_date = _first_matching_template_date(template, created_at.date())
    start_time_value = str(template["start_time"])
    end_time_value = str(template["end_time"])
    return {
        "academy_id": ACADEMY_ID,
        "session_id": session_id,
        "coach_id": coach_id,
        "title": template["name"],
        "location": template["location"],
        "capacity": template["max_students"],
        "amount_cents": amount_cents,
        "start_at": _local_datetime(representative_date, start_time_value, timezone_name),
        "end_at": _local_datetime(representative_date, end_time_value, timezone_name),
        "status": "scheduled",
        "is_deleted": False,
        "created_at": created_at,
        "days_of_week": list(template.get("days_of_week") or []),
        "start_time": start_time_value,
        "end_time": end_time_value,
        "timezone": timezone_name,
        "start_date": str(template.get("start_date") or representative_date.isoformat()),
        "end_date": str(template.get("end_date") or "2026-12-31"),
        "skill_level": template["skill_level"],
        "age_group": template["age_group"],
        "monthly_price": template["monthly_price"],
    }


def build_session_occurrence_docs(
    session_doc: dict[str, object],
    *,
    window_start: date,
    days_forward: int = 60,
    days_back: int = 0,
) -> list[dict[str, object]]:
    timezone_name = str(session_doc.get("timezone") or ACADEMY_TZ)
    active_start = _template_date(session_doc.get("start_date"))
    active_end = _template_date(session_doc.get("end_date"))
    current = window_start - timedelta(days=days_back)
    final = window_start + timedelta(days=days_forward)
    if active_start is not None:
        current = max(current, active_start)
    if active_end is not None:
        final = min(final, active_end)

    dow_ints = {
        DOW_MAP[str(day)[:3].title()]
        for day in list(session_doc.get("days_of_week") or [])
        if str(day)[:3].title() in DOW_MAP
    }
    if not dow_ints:
        return []

    session_id = str(session_doc["session_id"])
    start_time_value = str(session_doc["start_time"])
    end_time_value = str(session_doc["end_time"])
    rows: list[dict[str, object]] = []
    while current <= final:
        if current.weekday() in dow_ints:
            rows.append(
                {
                    "occurrence_id": f"{session_id}:{current.isoformat()}:{start_time_value[:5]}",
                    "academy_id": str(session_doc["academy_id"]),
                    "session_id": session_id,
                    "template_session_id": session_id,
                    "start_at": _local_datetime(current, start_time_value, timezone_name),
                    "end_at": _local_datetime(current, end_time_value, timezone_name),
                    "status": "scheduled",
                    "scheduled_coach_id": str(session_doc["coach_id"]),
                    "is_billable": True,
                    "is_payable": True,
                }
            )
        current += timedelta(days=1)
    return rows


def is_concrete_session_for_completion(session_doc: dict[str, object]) -> bool:
    return not bool(session_doc.get("days_of_week"))


def hp(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def now_str() -> str:
    return utcnow().isoformat()


def new_id() -> str:
    return str(new_ulid())


# ---------------------------------------------------------------------------
# Firebase emulator helpers
# ---------------------------------------------------------------------------


def _emulator_base() -> str:
    host = FIREBASE_EMULATOR.rstrip("/")
    if not host.startswith("http"):
        host = f"http://{host}"
    return host


def _emulator_request(path: str, payload: dict | None = None, method: str = "POST") -> dict:
    url = f"{_emulator_base()}{path}"
    data = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = json.loads(e.read())
        raise RuntimeError(body.get("error", {}).get("message", str(e))) from e


def firebase_clear_users() -> None:
    try:
        _emulator_request(
            f"/emulator/v1/projects/{FIREBASE_PROJECT}/accounts",
            method="DELETE",
            payload={},
        )
        print("  Firebase auth: cleared all users")
    except Exception as e:
        print(f"  Firebase auth clear skipped: {e}")


def firebase_create_user(email: str, password: str, display_name: str = "") -> str:
    """Create user in emulator with email pre-verified. Returns localId (Firebase UID)."""
    try:
        resp = _emulator_request(
            "/identitytoolkit.googleapis.com/v1/accounts:signUp?key=emulator-local",
            {
                "email": email,
                "password": password,
                "displayName": display_name,
                "returnSecureToken": True,
            },
        )
    except RuntimeError as e:
        if "EMAIL_EXISTS" in str(e):
            resp = _emulator_request(
                "/identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=emulator-local",
                {"email": email, "password": password, "returnSecureToken": True},
            )
        else:
            raise
    uid = resp["localId"]
    # Mark email verified via Admin SDK so backend password-provider email check passes.
    _init_firebase_admin()
    firebase_admin_auth.update_user(uid, email_verified=True)
    return uid


def firebase_available() -> bool:
    try:
        urllib.request.urlopen(
            f"{_emulator_base()}/identitytoolkit.googleapis.com/v1/accounts:lookup?key=emulator-local",
            timeout=2,
        )
    except urllib.error.HTTPError:
        return True  # reachable, just 400/403 on bad payload
    except Exception:
        return False
    return True


# ---------------------------------------------------------------------------
# Static data
# ---------------------------------------------------------------------------

SESSIONS = [
    {
        "name": "Thursday 6:00 PM – 6:45 PM Beginner(Coach - Gowtham)",
        "skill_level": "beginner",
        "age_group": "All",
        "start_date": "2026-04-01",
        "end_date": "2026-12-31",
        "days_of_week": ["Thu"],
        "start_time": "18:00",
        "end_time": "18:45",
        "location": "Court",
        "max_students": 15,
        "monthly_price": 60.0,
        "coach_key": "Gowtham",
    },
    {
        "name": "Wednesday 6:15 PM – 7:00 PM Intermediate(Coach - Kishore)",
        "skill_level": "intermediate",
        "age_group": "All",
        "start_date": "2026-04-01",
        "end_date": "2026-12-31",
        "days_of_week": ["Wed"],
        "start_time": "18:15",
        "end_time": "19:00",
        "location": "Court",
        "max_students": 15,
        "monthly_price": 70.0,
        "coach_key": "Kishore",
    },
    {
        "name": "Thursday 6:45 PM – 7:30 PM Intermediate(Coach - Gowtham)",
        "skill_level": "intermediate",
        "age_group": "All",
        "start_date": "2026-04-01",
        "end_date": "2026-12-31",
        "days_of_week": ["Thu"],
        "start_time": "18:45",
        "end_time": "19:30",
        "location": "Court",
        "max_students": 15,
        "monthly_price": 70.0,
        "coach_key": "Gowtham",
    },
    {
        "name": "Wednesday 5:45 PM – 6:30 PM Beginner(Coach - Kishore)",
        "skill_level": "beginner",
        "age_group": "All",
        "start_date": "2026-04-01",
        "end_date": "2026-12-31",
        "days_of_week": ["Wed"],
        "start_time": "17:45",
        "end_time": "18:30",
        "location": "Court",
        "max_students": 15,
        "monthly_price": 60.0,
        "coach_key": "Kishore",
    },
]

# (child_name, parent_name, parent_email, parent_phone,
#  age, skill, session_name, billing_type, student_status,
#  emergency_contact, medical, tshirt, prev_exp,
#  apr_enrolled, apr_paid, may_enrolled, may_paid)
ROSTER = [
    (
        "Nigazhini Manoj",
        "Manoj Edward",
        "manojedward.btech@gmail.com",
        "3095308920",
        6,
        "beginner",
        "Thursday 6:00 PM – 6:45 PM Beginner(Coach - Gowtham)",
        "Standard",
        "active",
        "Annie Jasmine: 3095855306",
        "None",
        "S",
        "None",
        True,
        60.0,
        True,
        60.0,
    ),
    (
        "Athiksha Sakthivel",
        "Sakthivel Shanmugam",
        "sakthivelplan@gmail.com",
        "3095326987",
        9,
        "beginner",
        "Wednesday 6:15 PM – 7:00 PM Intermediate(Coach - Kishore)",
        "Standard",
        "active",
        "Anitha 3095311987",
        "",
        "",
        "",
        True,
        None,
        True,
        None,
    ),
    (
        "Arjun V",
        "Viswanathan N",
        "viswanathan.kn@gmail.com",
        "3097507837",
        12,
        "intermediate",
        "Wednesday 6:15 PM – 7:00 PM Intermediate(Coach - Kishore)",
        "Standard",
        "active",
        "Viswa - 3097507837",
        "No",
        "M",
        "",
        True,
        70.0,
        True,
        70.0,
    ),
    (
        "Surya Balakrishnan",
        "Krishna Balakrishnan",
        "krishnaswamib@gmail.com",
        "2487033410",
        12,
        "intermediate",
        "Thursday 6:45 PM – 7:30 PM Intermediate(Coach - Gowtham)",
        "Standard",
        "active",
        "Krishna Balakrishnan 248-202-3031",
        "NA",
        "L",
        "Little bit",
        True,
        70.0,
        True,
        None,
    ),
    (
        "Harshith Bhaskar",
        "Mohana Anandhan",
        "monaa1384@gmail.com",
        "3093100227",
        13,
        "beginner",
        "Thursday 6:45 PM – 7:30 PM Intermediate(Coach - Gowtham)",
        "Standard",
        "active",
        "Bhaskar Hariharan",
        "",
        "",
        "Yes – playing for the last 1 month",
        True,
        70.0,
        True,
        70.0,
    ),
    (
        "Pradhyun Bhaskar",
        "Mohana Anandhan",
        "monaa1384@gmail.com",
        "3093100227",
        10,
        "beginner",
        "Thursday 6:45 PM – 7:30 PM Intermediate(Coach - Gowtham)",
        "Standard",
        "active",
        "Bhaksar 3096136568",
        "",
        "",
        "No – just playing recently 2 months",
        True,
        70.0,
        True,
        70.0,
    ),
    (
        "Netra Murugesan Ramya",
        "Murugesan Kollanur Palaniappan",
        "kpmpalaniappan@gmail.com",
        "3095315676",
        7,
        "beginner",
        "Wednesday 5:45 PM – 6:30 PM Beginner(Coach - Kishore)",
        "Standard",
        "active",
        "Murugesan - 3095315676",
        "Nil",
        "",
        "Nil",
        True,
        60.0,
        True,
        60.0,
    ),
    (
        "Hannah Sahaya Vinodh",
        "Sahaya Vinodh",
        "sahayavinodh@gmail.com",
        "3098077373",
        11,
        "intermediate",
        "Wednesday 6:15 PM – 7:00 PM Intermediate(Coach - Kishore)",
        "Standard",
        "hold",
        "Sahaya Vinodh - 309-807-7373",
        "",
        "",
        "8 weeks training in Bloomington",
        True,
        70.0,
        False,
        None,
    ),
    (
        "Vrushali Kariveda",
        "Rohith Kariveda",
        "rohith.myway@gmail.com",
        "8722029449",
        6,
        "beginner",
        "Thursday 6:00 PM – 6:45 PM Beginner(Coach - Gowtham)",
        "Standard",
        "active",
        "Divya - 3096125501",
        "",
        "",
        "None",
        True,
        60.0,
        True,
        60.0,
    ),
    (
        "Varshali Kariveda",
        "Rohith Kariveda",
        "rohith.myway@gmail.com",
        "8722029449",
        6,
        "beginner",
        "Thursday 6:00 PM – 6:45 PM Beginner(Coach - Gowtham)",
        "Standard",
        "active",
        "Divya 3096125501",
        "",
        "",
        "None",
        True,
        60.0,
        True,
        60.0,
    ),
    (
        "Sadhvi Amireddy",
        "Uvaraju Amireddy",
        "uvaraju.a@gmail.com",
        "3095314079",
        11,
        "beginner",
        "Wednesday 6:15 PM – 7:00 PM Intermediate(Coach - Kishore)",
        "Standard",
        "active",
        "Yuvaraj - 309-531-4079",
        "",
        "",
        "No",
        True,
        60.0,
        True,
        70.0,
    ),
    (
        "Jaanvi",
        "Raja Kakani",
        "rkakani8j378b@gmail.com",
        "7323575966",
        11,
        "beginner",
        "Thursday 6:45 PM – 7:30 PM Intermediate(Coach - Gowtham)",
        "Standard",
        "active",
        "Sri - (248) 885-9206",
        "",
        "",
        "Backyard play",
        True,
        70.0,
        True,
        70.0,
    ),
    (
        "Adhvik Saran",
        "Saran Maharajan",
        "saran.7176@gmail.com",
        "3093070358",
        8,
        "beginner",
        "Thursday 6:45 PM – 7:30 PM Intermediate(Coach - Gowtham)",
        "Standard",
        "active",
        "Saran Maharajan - 3093070358",
        "",
        "",
        "Minimum – can hit the cork",
        True,
        60.0,
        True,
        None,
    ),
    (
        "Jayaparthiban Jawaharbabu",
        "Jawaharbabu Jeyaraman",
        "jawaharbabuj@gmail.com",
        "3098254798",
        6,
        "beginner",
        "Wednesday 5:45 PM – 6:30 PM Beginner(Coach - Kishore)",
        "Standard",
        "active",
        "Jawaharbabu 3098254798",
        "",
        "",
        "Yes",
        True,
        60.0,
        True,
        60.0,
    ),
    (
        "Benjamin D'Mello",
        "Annalyn D'Mello",
        "annalynvaz@hotmail.com",
        "2242349703",
        12,
        "beginner",
        "Wednesday 6:15 PM – 7:00 PM Intermediate(Coach - Kishore)",
        "Standard",
        "active",
        "224-234-9703",
        "",
        "",
        "Introduction in PE",
        True,
        60.0,
        True,
        70.0,
    ),
    (
        "Jia Vidharthi Manoj Kumar",
        "Manoj Kumar M S",
        "msmanojreg@gmail.com",
        "3096125381",
        12,
        "intermediate",
        "Wednesday 6:15 PM – 7:00 PM Intermediate(Coach - Kishore)",
        "Standard",
        "active",
        "Manoj Kumar 3096125381",
        "",
        "",
        "Yes",
        True,
        70.0,
        True,
        None,
    ),
    (
        "Sakshi Kishore",
        "Kishore Subbarao",
        "kishoreraosubbarao@gmail.com",
        "3095318717",
        11,
        "beginner",
        "Thursday 6:45 PM – 7:30 PM Intermediate(Coach - Gowtham)",
        "NoCharge",
        "active",
        "Kishore Subbarao 3095318717",
        "",
        "",
        "Trained in trial first batch",
        True,
        None,
        True,
        None,
    ),
    (
        "Vehith Kishore",
        "Kishore Subbarao",
        "kishoreraosubbarao@gmail.com",
        "3095318717",
        7,
        "beginner",
        "Wednesday 6:15 PM – 7:00 PM Intermediate(Coach - Kishore)",
        "NoCharge",
        "active",
        "Kishore Subbarao 3095318717",
        "",
        "",
        "Trained in trial first batch",
        True,
        None,
        True,
        None,
    ),
    (
        "Akshaya Senthilkumar",
        "Senthilkumar Mohan Raj",
        "msenthilvpm@gmail.com",
        "3098319331",
        10,
        "beginner",
        "Thursday 6:00 PM – 6:45 PM Beginner(Coach - Gowtham)",
        "Standard",
        "active",
        "Senthilkumar 3098319331",
        "",
        "",
        "No",
        True,
        60.0,
        True,
        60.0,
    ),
    (
        "Viha Ramchand",
        "RamC Venkatasamy",
        "ramchand4685@gmail.com",
        "2488859243",
        10,
        "beginner",
        "Wednesday 6:15 PM – 7:00 PM Intermediate(Coach - Kishore)",
        "NoCharge",
        "active",
        "RamC - 2488859243",
        "",
        "",
        "Last Batch",
        True,
        None,
        True,
        None,
    ),
    (
        "Nilan Swaminathan Devi",
        "Devi Kumar",
        "devikv.devi@gmail.com",
        "3092054252",
        6,
        "beginner",
        "Wednesday 5:45 PM – 6:30 PM Beginner(Coach - Kishore)",
        "Standard",
        "active",
        "Devi Kumar - 3092054252",
        "",
        "",
        "None",
        True,
        60.0,
        True,
        None,
    ),
    (
        "Aryan LK",
        "Kumaran Thirunavukkarasu",
        "kumar.thirunavukarasu1@gmail.com",
        "3095315600",
        7,
        "beginner",
        "Wednesday 5:45 PM – 6:30 PM Beginner(Coach - Kishore)",
        "Standard",
        "active",
        "Kumaran 309-531-5600",
        "",
        "",
        "",
        True,
        None,
        True,
        60.0,
    ),
    (
        "Rihanth Sureshbabu",
        "Sureshbabu Dhandapani",
        "sureshbabu.dhandapani16@gmail.com",
        "3097509549",
        8,
        "intermediate",
        "Wednesday 6:15 PM – 7:00 PM Intermediate(Coach - Kishore)",
        "Standard",
        "active",
        "Sureshbabu 3098268755",
        "",
        "",
        "Yes",
        True,
        70.0,
        True,
        70.0,
    ),
    (
        "Suhaas Velaga",
        "Shravan Velaga",
        "velaga.shravan@gmail.com",
        "4255034059",
        6,
        "beginner",
        "Thursday 6:00 PM – 6:45 PM Beginner(Coach - Gowtham)",
        "Standard",
        "active",
        "Shravan Velaga 4255034059",
        "",
        "",
        "None",
        True,
        60.0,
        True,
        None,
    ),
    (
        "Aishani Tummala",
        "Sri Tummala",
        "vasu.0145@gmail.com",
        "2488859206",
        6,
        "beginner",
        "Wednesday 5:45 PM – 6:30 PM Beginner(Coach - Kishore)",
        "Standard",
        "dropped",
        "Sri Tummala",
        "",
        "",
        "None",
        True,
        60.0,
        False,
        None,
    ),
    (
        "Anjana Sana",
        "Adi Sekhara Reddy Sana",
        "adisekharreddy@gmail.com",
        "5756391240",
        9,
        "beginner",
        "Wednesday 5:45 PM – 6:30 PM Beginner(Coach - Kishore)",
        "Standard",
        "active",
        "Sri",
        "",
        "",
        "None",
        True,
        60.0,
        True,
        60.0,
    ),
    (
        "Abhishta Boddapati",
        "Prashanth Boddapati",
        "prasanthboddapati0805@gmail.com",
        "3095335123",
        10,
        "beginner",
        "Wednesday 5:45 PM – 6:30 PM Beginner(Coach - Kishore)",
        "Standard",
        "active",
        "Prashanth 3095335123",
        "",
        "",
        "No",
        True,
        60.0,
        True,
        None,
    ),
    (
        "Titiksha Vinothini Nirmalraj",
        "Nirmalraj",
        "nirmal16a@gmail.com",
        "3095315537",
        10,
        "beginner",
        "Thursday 6:45 PM – 7:30 PM Intermediate(Coach - Gowtham)",
        "Standard",
        "active",
        "Nirmalraj 3095315537",
        "",
        "",
        "",
        True,
        None,
        True,
        None,
    ),
    (
        "Shamshritha Shivanuri",
        "Prem Kumar Shivanuri",
        "shivanuriprem@gmail.com",
        "3092629464",
        6,
        "beginner",
        "Thursday 6:00 PM – 6:45 PM Beginner(Coach - Gowtham)",
        "Standard",
        "dropped",
        "Shivanuriprem 3093914950",
        "",
        "",
        "No",
        False,
        None,
        False,
        None,
    ),
    (
        "Prisha",
        "Srinivasa Ramanujan",
        "sudharsan1987@gmail.com",
        "3092054741",
        6,
        "beginner",
        "Wednesday 5:45 PM – 6:30 PM Beginner(Coach - Kishore)",
        "Standard",
        "active",
        "Srinivasa Ramanujan 3092054741",
        "",
        "",
        "No experience",
        True,
        60.0,
        True,
        60.0,
    ),
    (
        "Kabilan Chandran",
        "Jayachandran Mallika Ramachandran",
        "m.r.jayachandran@gmail.com",
        "5623666960",
        14,
        "intermediate",
        "Thursday 6:45 PM – 7:30 PM Intermediate(Coach - Gowtham)",
        "Standard",
        "active",
        "Jayachandran 7148203462",
        "",
        "",
        "Yes",
        True,
        70.0,
        True,
        70.0,
    ),
    (
        "Ethan Victor",
        "Victor Rajan",
        "mail2victors@gmail.com",
        "3093972925",
        14,
        "intermediate",
        "Thursday 6:45 PM – 7:30 PM Intermediate(Coach - Gowtham)",
        "Standard",
        "active",
        "Victor Rajan 309-397-2925",
        "",
        "",
        "",
        True,
        60.0,
        True,
        None,
    ),
    (
        "Diya Saggu",
        "Anil Saggu",
        "sr_anilkumar@yahoo.com",
        "6307305638",
        8,
        "beginner",
        "Wednesday 5:45 PM – 6:30 PM Beginner(Coach - Kishore)",
        "Standard",
        "active",
        "Anil Saggu 6307301506",
        "",
        "",
        "",
        True,
        35.0,
        True,
        60.0,
    ),
    (
        "Shakshitha Selvakumar",
        "Selvakumar Ramaiyah",
        "rselvakumarrsk@gmail.com",
        "3095300305",
        10,
        "intermediate",
        "Thursday 6:45 PM – 7:30 PM Intermediate(Coach - Gowtham)",
        "Standard",
        "active",
        "Sushmitha Nagarajan 3092051253",
        "",
        "",
        "Yes",
        True,
        70.0,
        True,
        None,
    ),
    (
        "Yantraa Santosh",
        "Santosh Subramanian",
        "san6031@gmail.com",
        "3095324552",
        7,
        "beginner",
        "Thursday 6:00 PM – 6:45 PM Beginner(Coach - Gowtham)",
        "Standard",
        "active",
        "Santosh Subramanian 3095324552",
        "",
        "",
        "None",
        True,
        60.0,
        True,
        60.0,
    ),
    (
        "Vishwesh Srikanth",
        "Srikanth Marikkannu",
        "srimarikk@gmail.com",
        "3096602532",
        15,
        "intermediate",
        "Thursday 6:45 PM – 7:30 PM Intermediate(Coach - Gowtham)",
        "Standard",
        "active",
        "Srikanth Marikkannu 3096602532",
        "",
        "",
        "Yes",
        True,
        70.0,
        True,
        None,
    ),
    (
        "Ananyhaa Sudhakar",
        "Sudhakar Panneerselvam",
        "f1sudhakar@gmail.com",
        "2012388279",
        13,
        "beginner",
        "Thursday 6:00 PM – 6:45 PM Beginner(Coach - Gowtham)",
        "Standard",
        "active",
        "Sudhakar 2012388279",
        "",
        "",
        "No",
        False,
        None,
        True,
        70.0,
    ),
    (
        "Maithri Kandula",
        "Mahesh Kandula",
        "mahesh.kandula34@gmail.com",
        "5713635113",
        6,
        "beginner",
        "Thursday 6:00 PM – 6:45 PM Beginner(Coach - Gowtham)",
        "Standard",
        "active",
        "Mahesh Kandula 5713635113",
        "",
        "",
        "",
        True,
        None,
        True,
        80.0,
    ),
    (
        "Harini Manikandan",
        "Mohana Divya Lalitha Gunasekaran",
        "mohanadivya15@gmail.com",
        "3095855661",
        14,
        "beginner",
        "Wednesday 6:15 PM – 7:00 PM Intermediate(Coach - Kishore)",
        "Standard",
        "active",
        "Mohana Divya 3095855661",
        "",
        "",
        "Played with her father",
        False,
        None,
        True,
        70.0,
    ),
    (
        "Pooja Naran",
        "Maran Mani",
        "maran27.mani@gmail.com",
        "3094344206",
        11,
        "beginner",
        "Wednesday 6:15 PM – 7:00 PM Intermediate(Coach - Kishore)",
        "Standard",
        "active",
        "Maran Mani 3094595111",
        "",
        "",
        "No",
        False,
        None,
        True,
        60.0,
    ),
    (
        "Divina",
        "David Jacob",
        "davidgentleguy@gmail.com",
        "3097504827",
        13,
        "intermediate",
        "Wednesday 6:15 PM – 7:00 PM Intermediate(Coach - Kishore)",
        "Standard",
        "active",
        "Dhivya David 3096605719",
        "",
        "",
        "",
        False,
        None,
        True,
        70.0,
    ),
    (
        "Radhesh Saravanan",
        "Saravanan Ramakrishnan",
        "saravananoff@hotmail.com",
        "3095320232",
        12,
        "beginner",
        "Thursday 6:00 PM – 6:45 PM Beginner(Coach - Gowtham)",
        "Standard",
        "active",
        "Saravanan 3095320232",
        "",
        "",
        "Nil",
        False,
        None,
        True,
        None,
    ),
    (
        "Dhanesh Saravanan",
        "Saravanan Ramakrishnan",
        "saravananoff@hotmail.com",
        "3095320232",
        10,
        "beginner",
        "Thursday 6:00 PM – 6:45 PM Beginner(Coach - Gowtham)",
        "Standard",
        "active",
        "Saravanan 3095320232",
        "",
        "",
        "Nil",
        False,
        None,
        True,
        None,
    ),
    (
        "Aadhya Abhishek",
        "Abhishek Ajithkumar",
        "abhishekak.off@gmail.com",
        "3095315171",
        7,
        "beginner",
        "Wednesday 5:45 PM – 6:30 PM Beginner(Coach - Kishore)",
        "Standard",
        "active",
        "Bavithra 3095325547",
        "",
        "",
        "Na",
        False,
        None,
        True,
        60.0,
    ),
    (
        "Kavishayashree Senthilkumar",
        "Senthilkumar Krishnan",
        "spsfamily7428@gmail.com",
        "3096848687",
        7,
        "beginner",
        "Wednesday 5:45 PM – 6:30 PM Beginner(Coach - Kishore)",
        "Standard",
        "active",
        "Abhishek 3095315171",
        "",
        "",
        "None",
        False,
        None,
        True,
        60.0,
    ),
    (
        "Riaan Pitale",
        "Rashmi Pitale",
        "rashmi.luniya@gmail.com",
        "3095313691",
        8,
        "beginner",
        "Thursday 6:00 PM – 6:45 PM Beginner(Coach - Gowtham)",
        "Standard",
        "active",
        "Rashmi Pitale 3095330354",
        "",
        "",
        "New to sport",
        False,
        None,
        True,
        None,
    ),
]

ATTENDANCE_LOG = [
    # (date, session_name, student_name, status)
    (
        "2026-05-07",
        "Wednesday 5:45 PM – 6:30 PM Beginner(Coach - Kishore)",
        "Netra Murugesan Ramya",
        "present",
    ),
    (
        "2026-05-07",
        "Wednesday 5:45 PM – 6:30 PM Beginner(Coach - Kishore)",
        "Jayaparthiban Jawaharbabu",
        "present",
    ),
    (
        "2026-05-07",
        "Wednesday 5:45 PM – 6:30 PM Beginner(Coach - Kishore)",
        "Nilan Swaminathan Devi",
        "present",
    ),
    ("2026-05-07", "Wednesday 5:45 PM – 6:30 PM Beginner(Coach - Kishore)", "Aryan LK", "present"),
    (
        "2026-05-07",
        "Wednesday 5:45 PM – 6:30 PM Beginner(Coach - Kishore)",
        "Anjana Sana",
        "present",
    ),
    (
        "2026-05-07",
        "Wednesday 5:45 PM – 6:30 PM Beginner(Coach - Kishore)",
        "Abhishta Boddapati",
        "present",
    ),
    ("2026-05-07", "Wednesday 5:45 PM – 6:30 PM Beginner(Coach - Kishore)", "Prisha", "present"),
    (
        "2026-05-07",
        "Wednesday 5:45 PM – 6:30 PM Beginner(Coach - Kishore)",
        "Diya Saggu",
        "present",
    ),
]

MOVE_LOG = [
    # (kid, from_session, to_session, effective_period, permanent)
    (
        "Ananyhaa Sudhakar",
        "Thursday 6:00 PM – 6:45 PM Beginner(Coach - Gowtham)",
        "Thursday 6:45 PM – 7:30 PM Intermediate(Coach - Gowtham)",
        "2026-05",
        True,
    ),
    (
        "Jayaparthiban Jawaharbabu",
        "Thursday 6:00 PM – 6:45 PM Beginner(Coach - Gowtham)",
        "Wednesday 5:45 PM – 6:30 PM Beginner(Coach - Kishore)",
        "2026-05",
        True,
    ),
    (
        "Harshith Bhaskar",
        "Thursday 6:45 PM – 7:30 PM Intermediate(Coach - Gowtham)",
        "Thursday 6:45 PM – 7:30 PM Intermediate(Coach - Gowtham)",
        "2026-04",
        True,
    ),
]

# category must match v2 Expense Literal["rent","equipment","salary","marketing","other"]
EXPENSES = [
    {
        "category": "rent",
        "note": "Monthly rent – Apr 2026",
        "amount_cents": 80000,
        "date": "2026-04-01",
    },
    {
        "category": "rent",
        "note": "Monthly rent – May 2026",
        "amount_cents": 80000,
        "date": "2026-05-01",
    },
    {
        "category": "other",
        "note": "Other expenses – Apr 2026",
        "amount_cents": 15000,
        "date": "2026-04-01",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def split_name(full: str) -> tuple[str, str]:
    parts = full.strip().split()
    if len(parts) <= 1:
        return (parts[0] if parts else ""), ""
    return parts[0], " ".join(parts[1:])


def age_to_dob(age: int) -> str:
    if not age:
        return ""
    return (datetime.now() - timedelta(days=365 * age)).strftime("%Y-%m-%d")


def _parse_emergency_phone(raw: str) -> str:
    found = re.findall(r"\d[\d\s\-]{7,}", raw)
    return found[0].strip() if found else raw


async def _upsert_seed_ledger_records(db, payment_doc: dict) -> None:
    mapped = map_legacy_payment(payment_doc)
    if mapped is None:
        return

    invoice = mapped["invoice"]
    line = mapped["line"]
    ledger_payment = mapped["ledger_payment"]
    allocation = mapped["allocation"]

    await db.invoices.update_one(
        {"academy_id": invoice["academy_id"], "invoice_id": invoice["invoice_id"]},
        {"$set": invoice},
        upsert=True,
    )
    await db.invoice_lines.update_one(
        {"academy_id": line["academy_id"], "line_id": line["line_id"]},
        {"$set": line},
        upsert=True,
    )
    if ledger_payment:
        await db.ledger_payments.update_one(
            {
                "academy_id": ledger_payment["academy_id"],
                "payment_id": ledger_payment["payment_id"],
            },
            {"$set": ledger_payment},
            upsert=True,
        )
    if allocation:
        await db.payment_allocations.update_one(
            {
                "academy_id": allocation["academy_id"],
                "allocation_id": allocation["allocation_id"],
            },
            {"$set": allocation},
            upsert=True,
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    mongo_url = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
    db_name = os.environ.get("DB_NAME", "academy_manager_local")
    db = AsyncIOMotorClient(mongo_url)[db_name]

    print(f"Seeding {db_name} at {mongo_url}")
    print(f"Firebase mode: {FIREBASE_MODE}  |  Academy: {ACADEMY_ID}")

    # ── Firebase emulator: clear & recreate users ──────────────────────────
    firebase_uid_map: dict[str, str] = {}  # email → firebase_uid
    if FIREBASE_MODE:
        if firebase_available():
            print("Firebase emulator reachable — clearing users")
            firebase_clear_users()
        else:
            print("WARNING: Firebase emulator not reachable; skipping auth user creation")

    admin_email = os.environ.get("ADMIN_EMAIL", "ramchand4685@gmail.com").lower()

    # ── 1. Drop transactional collections; keep admin user ─────────────────
    for col in (
        "academies",
        "academy_settings",
        "academy_memberships",
        "sessions",
        "session_occurrences",
        "students",
        "enrollments",
        "payments",
        "invoices",
        "invoice_lines",
        "ledger_payments",
        "payment_allocations",
        "account_credit_ledger",
        "credit_applications",
        "payment_attempts",
        "parent_billing_customers",
        "legacy_payments_archive",
        "expenses",
        "attendance",
        "lesson_plans",
        "progress_notes",
        "coach_payouts",
        "payout_rules",
        "move_log",
        "messages",
        "notifications",
        "invites",
        "audit_logs",
        "waivers",
        "waiver_versions",
        "waiver_acceptances",
        "platform_roles",
        "skill_programs",
        "skill_levels",
        "skills",
        "skill_criteria",
        "external_lesson_refs",
        "student_level_progress",
        "student_skill_progress",
        "test_attempts",
        "level_up_recommendations",
        "skill_certificates",
    ):
        await db[col].drop()
    await db.users.delete_many({"email": {"$ne": admin_email}})
    print("Cleared collections.")

    # ── 1a. Academy doc (Settings panels read/write this) ─────────────────
    await db.academies.update_one(
        {"_id": ACADEMY_ID},
        {
            "$set": {
                "_id": ACADEMY_ID,
                "slug": ACADEMY_ID,
                "academy_id": ACADEMY_ID,
                "display_name": ACADEMY_NAME,
                "timezone": ACADEMY_TZ,
                "contact_email": admin_email,
                "contact_phone": None,
                "hours_text": "Wed 6:15pm–7:30pm · Thu 6:00pm–9:30pm",
                "address": None,
                "created_at": utcnow(),
                "updated_at": utcnow(),
            }
        },
        upsert=True,
    )
    print(f"Academy: {ACADEMY_NAME!r} ({ACADEMY_ID}, tz={ACADEMY_TZ})")

    await db.academy_settings.update_one(
        {"academy_id": ACADEMY_ID},
        {
            "$set": {
                "settings_id": f"set_{ACADEMY_ID}",
                "academy_id": ACADEMY_ID,
                "display_name": ACADEMY_NAME,
                "timezone": ACADEMY_TZ,
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
                },
                "created_at": utcnow(),
                "updated_at": utcnow(),
            }
        },
        upsert=True,
    )

    # ── Ensure admin user has v2 fields ────────────────────────────────────
    admin_firebase_uid = ""
    if FIREBASE_MODE and firebase_available():
        admin_firebase_uid = firebase_create_user(admin_email, ADMIN_PASSWORD, "Admin")
        firebase_uid_map[admin_email] = admin_firebase_uid
        print(f"  Firebase admin uid: {admin_firebase_uid[:16]}...")
    admin_doc = await db.users.find_one({"email": admin_email})
    if admin_doc:
        await db.users.update_one(
            {"_id": admin_doc["_id"]},
            {
                "$set": {
                    "academy_id": ACADEMY_ID,
                    # Owner/admin split: the seeded admin is the academy owner.
                    "role": "admin",
                    "roles": ["admin", "owner"],
                    "display_name": admin_doc.get("display_name")
                    or admin_doc.get("name")
                    or "Admin",
                    "user_id": admin_firebase_uid or str(admin_doc["_id"]),
                    "firebase_uid": admin_firebase_uid or str(admin_doc["_id"]),
                },
                "$unset": {"stripe_customer_id": ""},
            },
        )
    else:
        doc: dict = {
            "academy_id": ACADEMY_ID,
            "email": admin_email,
            "display_name": "Admin",
            "name": "Admin",
            "role": "admin",
            "roles": ["admin", "owner"],
            "status": "active",
            "is_active": True,
            "stripe_customer_id": None,
            "created_at": utcnow(),
            "updated_at": utcnow(),
        }
        if admin_firebase_uid:
            doc["user_id"] = admin_firebase_uid
            doc["firebase_uid"] = admin_firebase_uid
        else:
            doc["password_hash"] = hp(ADMIN_PASSWORD)
        r = await db.users.insert_one(doc)
        if not admin_firebase_uid:
            await db.users.update_one(
                {"_id": r.inserted_id},
                {"$set": {"user_id": str(r.inserted_id), "firebase_uid": str(r.inserted_id)}},
            )

    # ── 1b. Grant platform_admin to admin user ─────────────────────────────
    admin_doc_fresh = await db.users.find_one({"email": admin_email})
    if admin_doc_fresh:
        admin_uid_final = str(
            admin_doc_fresh.get("user_id")
            or admin_doc_fresh.get("firebase_uid")
            or admin_doc_fresh["_id"]
        )
        await db.platform_roles.update_one(
            {"user_id": admin_uid_final, "role": "platform_admin"},
            {
                "$set": {
                    "user_id": admin_uid_final,
                    "role": "platform_admin",
                    "status": "active",
                    "granted_at": utcnow(),
                },
                "$setOnInsert": {"platform_role_id": new_ulid(), "created_at": utcnow()},
            },
            upsert=True,
        )
        print(f"  Platform admin: {admin_email} -> platform_roles.platform_admin")

    # ── 1c. Admin-only operations user ─────────────────────────────────────
    # A post-split admin: holds `admin` but not `owner`, so locally you can
    # see the operations view (no refunds, pricing, payouts, reports, audit,
    # or admin/owner grants) next to the owner account above. Step 10 turns
    # `roles` into the academy_memberships row.
    ops_email = "ops@blno.academy"
    if not await db.users.find_one({"email": ops_email}):
        ops_uid = ""
        if FIREBASE_MODE and firebase_available():
            ops_uid = firebase_create_user(ops_email, ADMIN_PASSWORD, "Ops Admin")
            firebase_uid_map[ops_email] = ops_uid
        ops_doc: dict = {
            "academy_id": ACADEMY_ID,
            "email": ops_email,
            "display_name": "Ops Admin",
            "name": "Ops Admin",
            "role": "admin",
            "roles": ["admin"],
            "status": "active",
            "is_active": True,
            "stripe_customer_id": None,
            "created_at": utcnow(),
            "updated_at": utcnow(),
        }
        if ops_uid:
            ops_doc["user_id"] = ops_uid
            ops_doc["firebase_uid"] = ops_uid
        else:
            ops_doc["password_hash"] = hp(ADMIN_PASSWORD)
        r = await db.users.insert_one(ops_doc)
        if not ops_uid:
            await db.users.update_one(
                {"_id": r.inserted_id},
                {"$set": {"user_id": str(r.inserted_id), "firebase_uid": str(r.inserted_id)}},
            )
        print(f"  Admin-only user: {ops_email} (roles=['admin'], no owner)")

    # ── 2. Coaches ──────────────────────────────────────────────────────────
    coach_info = {
        "Gowtham": {"email": "gowtham@blno.academy", "display_name": "Gowtham"},
        "Kishore": {"email": "kishore@blno.academy", "display_name": "Kishore"},
    }
    coach_ids: dict[str, str] = {}
    for cname, cinfo in coach_info.items():
        cemail = cinfo["email"]
        firebase_uid = ""
        if FIREBASE_MODE and firebase_available():
            firebase_uid = firebase_create_user(cemail, COACH_PASSWORD, cname)
            firebase_uid_map[cemail] = firebase_uid
        doc = {
            "academy_id": ACADEMY_ID,
            "email": cemail,
            "display_name": cname,
            "name": cname,
            "role": "coach",
            "roles": ["coach"],
            "status": "active",
            "is_active": True,
            "stripe_customer_id": None,
            "created_at": utcnow(),
            "updated_at": utcnow(),
        }
        if firebase_uid:
            doc["user_id"] = firebase_uid
            doc["firebase_uid"] = firebase_uid
        else:
            doc["password_hash"] = hp(COACH_PASSWORD)
        r = await db.users.insert_one(doc)
        uid = firebase_uid or str(r.inserted_id)
        if not firebase_uid:
            await db.users.update_one(
                {"_id": r.inserted_id}, {"$set": {"user_id": uid, "firebase_uid": uid}}
            )
        coach_ids[cname] = uid
    print(f"Coaches: {list(coach_ids.keys())}")

    # ── 3. Payout rules ─────────────────────────────────────────────────────
    for cid in coach_ids.values():
        await db.payout_rules.insert_one(
            {
                "academy_id": ACADEMY_ID,
                "coach_id": cid,
                "rule_type": "revenue_percentage",
                "value": 30,
                "is_active": True,
                "created_at": utcnow(),
            }
        )

    # ── 4. Waiver ────────────────────────────────────────────────────────────
    # MongoRegistrationWaiverRepository reads waiver_templates where
    # status=="active" and assigned_to_registration==True.
    _waiver_text = "I, the parent/guardian, have read and agree to the BlNo Badminton Academy Liability Waiver."
    _waiver_template_id = new_id()
    _waiver_hash = hashlib.sha256(_waiver_text.encode()).hexdigest()
    _waiver_published_at = datetime(2026, 4, 1, tzinfo=timezone.utc)
    waiver_r = await db.waiver_templates.insert_one(
        {
            "academy_id": ACADEMY_ID,
            "waiver_template_id": _waiver_template_id,
            "name": "Standard Liability Waiver",
            "version": "2026.1",
            "body": _waiver_text,
            "content_hash": _waiver_hash,
            "effective_from": _waiver_published_at,
            "status": "active",
            "assigned_to_registration": True,
            "assigned_at": _waiver_published_at,
            "published_at": _waiver_published_at,
            "updated_at": utcnow(),
            "created_at": utcnow(),
        }
    )
    waiver_version_id = str(waiver_r.inserted_id)

    # ── 5. Sessions ─────────────────────────────────────────────────────────
    # Weekly classes are stored as recurring templates. Dated class instances
    # live in session_occurrences for the maintained local testing window.
    today = datetime.now(timezone.utc).date()
    session_ids: dict[str, str] = {}
    total_occurrences = 0
    for s in SESSIONS:
        coach_id = coach_ids[s["coach_key"]]
        amount_cents = int(s["monthly_price"] * 100)
        session_id = new_id()
        doc = build_recurring_session_doc(
            s,
            session_id=session_id,
            coach_id=coach_id,
            amount_cents=amount_cents,
            created_at=utcnow(),
        )
        await db.sessions.insert_one(doc)
        session_ids[s["name"]] = session_id

        for occurrence in build_session_occurrence_docs(
            doc,
            window_start=today,
            days_back=35,
            days_forward=60,
        ):
            await db.session_occurrences.update_one(
                {"occurrence_id": occurrence["occurrence_id"], "academy_id": ACADEMY_ID},
                {"$setOnInsert": occurrence},
                upsert=True,
            )
            total_occurrences += 1
    print(f"Sessions: {len(session_ids)} recurring templates, {total_occurrences} occurrences")

    # ── Past sessions: mark completed + seed occurrences for payout ──────────
    today_dt = datetime.now(timezone.utc)
    past_sessions = await db.sessions.find(
        {
            "academy_id": ACADEMY_ID,
            "start_at": {"$lt": today_dt},
            "$or": [{"days_of_week": {"$exists": False}}, {"days_of_week": []}],
        }
    ).to_list(length=None)

    occurrence_count = 0
    for sess in past_sessions:
        if not is_concrete_session_for_completion(sess):
            continue
        sid = str(sess.get("session_id") or sess["_id"])
        coach_id = str(sess.get("coach_id", ""))
        await db.sessions.update_one(
            {"_id": sess["_id"]},
            {"$set": {"status": "completed", "is_payable": True}},
        )
        await db.session_occurrences.update_one(
            {"occurrence_id": sid, "academy_id": ACADEMY_ID},
            {
                "$set": {
                    "start_at": sess.get("start_at"),
                    "end_at": sess.get("end_at", sess.get("start_at")),
                    "status": "completed",
                    "scheduled_coach_id": coach_id,
                    "is_billable": True,
                    "is_payable": True,
                },
                "$setOnInsert": {
                    "occurrence_id": sid,
                    "academy_id": ACADEMY_ID,
                    "session_id": sid,
                    "template_session_id": sid,
                },
            },
            upsert=True,
        )
        occurrence_count += 1
    completed_occurrences = await db.session_occurrences.update_many(
        {"academy_id": ACADEMY_ID, "start_at": {"$lt": today_dt}},
        {"$set": {"status": "completed", "is_billable": True, "is_payable": True}},
    )
    print(
        "  Past occurrences completed+seeded: "
        f"{occurrence_count + completed_occurrences.modified_count}"
    )

    # ── Coach rates (per-session billing) ────────────────────────────────────
    effective_from_dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rates_seeded = 0
    for cname, coach_uid in coach_ids.items():
        if not coach_uid:
            continue
        await db.coach_rates.update_one(
            {"academy_id": ACADEMY_ID, "coach_id": coach_uid, "status": "active"},
            {
                "$setOnInsert": {
                    "rate_id": new_id(),
                    "academy_id": ACADEMY_ID,
                    "coach_id": coach_uid,
                    "billing_unit": "per_session",
                    "amount_minor": 2500,
                    "currency": "usd",
                    "effective_from": effective_from_dt,
                    "effective_until": None,
                    "status": "active",
                }
            },
            upsert=True,
        )
        rates_seeded += 1
    print(f"  Coach rates seeded: {rates_seeded}")

    # ── 6. Parents / Students / Enrollments / Payments ─────────────────────
    parent_id_by_email: dict[str, str] = {}
    student_id_by_name: dict[str, str] = {}
    enrollment_count = payment_count = 0

    for row in ROSTER:
        (
            child,
            parent_display,
            email,
            phone,
            age,
            skill,
            session_name,
            billing_type,
            stu_status,
            emergency,
            medical,
            tshirt,
            prev_exp,
            apr_enr,
            apr_paid,
            may_enr,
            may_paid,
        ) = row

        email = email.lower()

        # ── Parent user ──
        if email not in parent_id_by_email:
            existing = await db.users.find_one({"email": email})
            if existing:
                # Backfill v2 fields if missing
                parent_id_by_email[email] = str(existing.get("user_id") or existing["_id"])
                await db.users.update_one(
                    {"_id": existing["_id"]},
                    {
                        "$set": {
                            "academy_id": ACADEMY_ID,
                            "display_name": existing.get("display_name")
                            or existing.get("name")
                            or parent_display,
                        },
                        "$unset": {"stripe_customer_id": ""},
                    },
                )
            else:
                firebase_uid = ""
                if FIREBASE_MODE and firebase_available():
                    firebase_uid = firebase_create_user(email, PARENT_PASSWORD, parent_display)
                    firebase_uid_map[email] = firebase_uid
                doc = {
                    "academy_id": ACADEMY_ID,
                    "email": email,
                    "display_name": parent_display,
                    "name": parent_display,
                    "phone": phone,
                    "role": "parent",
                    "roles": ["parent"],
                    "status": "active",
                    "is_active": True,
                    "stripe_customer_id": None,
                    "created_at": utcnow(),
                    "updated_at": utcnow(),
                }
                if firebase_uid:
                    doc["user_id"] = firebase_uid
                    doc["firebase_uid"] = firebase_uid
                else:
                    doc["password_hash"] = hp(PARENT_PASSWORD)
                r = await db.users.insert_one(doc)
                uid = firebase_uid or str(r.inserted_id)
                if not firebase_uid:
                    await db.users.update_one(
                        {"_id": r.inserted_id}, {"$set": {"user_id": uid, "firebase_uid": uid}}
                    )
                parent_id_by_email[email] = uid
        parent_id = parent_id_by_email[email]
        await db.parent_billing_customers.update_one(
            {"academy_id": ACADEMY_ID, "parent_id": parent_id},
            {
                "$setOnInsert": {
                    "academy_id": ACADEMY_ID,
                    "parent_id": parent_id,
                    "created_at": utcnow(),
                },
                "$set": {"updated_at": utcnow()},
            },
            upsert=True,
        )

        # ── Student ──
        first, last = split_name(child)
        full_name = f"{first} {last}".strip()
        student_id = new_id()
        stu_doc = {
            "academy_id": ACADEMY_ID,
            "student_id": student_id,
            "first_name": first,
            "last_name": last,
            "full_name": full_name,
            "dob": age_to_dob(age),
            "age": age,
            "skill_level": skill,
            "emergency_contact_name": emergency.split(":")[0].split("-")[0].strip()[:80],
            "emergency_contact_phone": _parse_emergency_phone(emergency),
            "medical_notes": medical or "",
            "t_shirt_size": tshirt or "",
            "previous_experience": prev_exp or "",
            "waiver_accepted": True,
            "waiver_date": utcnow(),
            "parent_id": parent_id,
            "parent_user_id": parent_id,
            "status": stu_status,
            "is_deleted": False,
            "created_at": utcnow(),
        }
        await db.students.insert_one(stu_doc)
        student_id_by_name[child.lower()] = student_id

        await db.waiver_acceptances.insert_one(
            {
                "academy_id": ACADEMY_ID,
                "student_id": student_id,
                "parent_id": parent_id,
                "parent_user_id": parent_id,
                "accepted_by_user_id": parent_id,
                "waiver_version_id": waiver_version_id,
                "accepted_at": utcnow(),
                "ip_address": "127.0.0.1",
            }
        )

        # ── Enrollment ──
        sid = session_ids.get(session_name)
        if not sid:
            print(f"  WARN: session not found for {child!r}: {session_name!r}")
            continue

        enrollment_id = new_id()
        en_doc = {
            "academy_id": ACADEMY_ID,
            "enrollment_id": enrollment_id,
            "session_id": sid,
            "student_id": student_id,
            "parent_id": parent_id,
            "parent_user_id": parent_id,
            "billing_type": billing_type,
            "approval_status": "approved",
            "status": "active",
            "enrolled_at": utcnow(),
            "is_deleted": False,
        }
        await db.enrollments.insert_one(en_doc)
        enrollment_count += 1

        # ── Billing ledger ──
        session_price_cents = int(
            next(s["monthly_price"] for s in SESSIONS if s["name"] == session_name) * 100
        )
        if billing_type == "Standard":
            for enrolled, paid_raw, period in (
                (apr_enr, apr_paid, "2026-04"),
                (may_enr, may_paid, "2026-05"),
            ):
                if not enrolled:
                    continue
                paid_cents = int(paid_raw * 100) if paid_raw else 0
                is_paid = paid_cents >= session_price_cents
                partial = 0 < paid_cents < session_price_cents
                payment_id = new_id()
                pay_doc = {
                    "academy_id": ACADEMY_ID,
                    "payment_id": payment_id,
                    "parent_id": parent_id,
                    "parent_user_id": parent_id,
                    "student_id": student_id,
                    "enrollment_id": enrollment_id,
                    "session_id": sid,
                    "period": period,
                    "amount_cents": session_price_cents,
                    "discount_cents": 0,
                    "final_amount_cents": session_price_cents,
                    "currency": "usd",
                    "status": "succeeded" if is_paid else "pending",
                    "refunded_cents": 0,
                    "payment_method": "Zelle" if is_paid else None,
                    "partial_paid_cents": paid_cents if partial else None,
                    "notes": "seeded",
                    "is_deleted": False,
                    "invoice_number": f"INV-{period.replace('-', '')}-{payment_id[-6:]}",
                    "created_at": utcnow(),
                    "updated_at": utcnow(),
                }
                if is_paid:
                    pay_doc["paid_at"] = utcnow()
                    pay_doc["payment_date"] = utcnow()
                await _upsert_seed_ledger_records(db, pay_doc)
                payment_count += 1

    print(
        f"Parents: {len(parent_id_by_email)}, Students: {len(student_id_by_name)}, "
        f"Enrollments: {enrollment_count}, Invoices: {payment_count}"
    )

    # ── 7. Attendance ───────────────────────────────────────────────────────
    attn_count = 0
    for attn_date, session_name, student_name, status in ATTENDANCE_LOG:
        stu_id = student_id_by_name.get(student_name.lower())
        sid = session_ids.get(session_name)
        if not (stu_id and sid):
            print(f"  WARN: attendance skip – {student_name!r}")
            continue
        coach_key = next(s["coach_key"] for s in SESSIONS if s["name"] == session_name)
        await db.attendance.update_one(
            {"session_id": sid, "student_id": stu_id, "date": attn_date},
            {
                "$set": {
                    "academy_id": ACADEMY_ID,
                    "session_id": sid,
                    "student_id": stu_id,
                    "date": attn_date,
                    "status": status,
                    "notes": "",
                    "marked_by": coach_ids.get(coach_key),
                    "marked_at": utcnow(),
                }
            },
            upsert=True,
        )
        attn_count += 1
    print(f"Attendance: {attn_count}")

    # ── 8. Move log ─────────────────────────────────────────────────────────
    for kid, from_name, to_name, period, permanent in MOVE_LOG:
        stu_id = student_id_by_name.get(kid.lower())
        from_sid = session_ids.get(from_name)
        to_sid = session_ids.get(to_name)
        if not (stu_id and from_sid and to_sid):
            continue
        await db.move_log.insert_one(
            {
                "academy_id": ACADEMY_ID,
                "student_id": stu_id,
                "from_session_id": from_sid,
                "to_session_id": to_sid,
                "effective_month": period,
                "permanent": permanent,
                "note": "seeded",
                "moved_by": None,
                "moved_at": utcnow(),
            }
        )
    print(f"Move log: {len(MOVE_LOG)}")

    # ── 9. Expenses ─────────────────────────────────────────────────────────
    for e in EXPENSES:
        expense_id = new_id()
        incurred = datetime.fromisoformat(e["date"]).replace(tzinfo=timezone.utc)
        await db.expenses.insert_one(
            {
                "academy_id": ACADEMY_ID,
                "expense_id": expense_id,
                "category": e["category"],
                "amount_cents": e["amount_cents"],
                "note": e["note"],
                "incurred_on": incurred,
                "is_deleted": False,
                "created_at": utcnow(),
            }
        )
    print(f"Expenses: {len(EXPENSES)}")

    # ── 10. Academy memberships ──────────────────────────────────────────────
    # Required by the SaaS auth middleware: every user needs an active
    # academy_memberships row or login returns MembershipNotFound (401).
    all_users = await db.users.find({"academy_id": ACADEMY_ID}).to_list(None)
    membership_count = 0
    now = utcnow()
    for u in all_users:
        uid = u.get("user_id") or u.get("firebase_uid") or str(u["_id"])
        raw_roles = u.get("roles", [])
        roles = list(raw_roles) if raw_roles else ["parent"]
        await db["academy_memberships"].update_one(
            {"academy_id": ACADEMY_ID, "user_id": uid},
            {
                "$set": {"roles": roles, "status": "active", "updated_at": now},
                "$setOnInsert": {
                    "membership_id": new_ulid(),
                    "academy_id": ACADEMY_ID,
                    "user_id": uid,
                    "invited_by": uid,
                    "invited_at": now,
                    "accepted_at": now,
                    "created_at": now,
                },
            },
            upsert=True,
        )
        membership_count += 1
    print(f"Memberships: {membership_count}")

    print("\n✓ Seed complete.")
    print(f"\nLogin credentials:")
    print(f"  Admin (platform_admin):  {admin_email} / {ADMIN_PASSWORD}")
    if FIREBASE_MODE:
        print(f"  Coach:  gowtham@blno.academy | kishore@blno.academy  /  {COACH_PASSWORD}")
        print(f"  Parent: <any parent email>  /  {PARENT_PASSWORD}")
    else:
        print(f"  Coach:  gowtham@blno.academy | kishore@blno.academy  /  {COACH_PASSWORD}")
        print(f"  Parent: <any parent email>  /  {PARENT_PASSWORD}")


if __name__ == "__main__":
    asyncio.run(main())
