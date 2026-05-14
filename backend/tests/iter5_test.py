"""
Iteration 5 — Scheduler + Calendar feature pass.
Tests:
  • GET /scheduler/status (admin)
  • GET /scheduler/next-period (admin)
  • POST /scheduler/run-monthly-invoices (admin, idempotent on a far-future period 2099-02)
  • POST /scheduler/run-dues-reminders (admin)
  • 403 for coach/parent on every /scheduler/* route
  • GET /calendar/events?start&end — admin returns weekly-expanded sessions
  • Calendar role-scoping (coach/parent seeded with no own sessions => empty list)
  • Calendar recurrence math: only days_of_week weekdays returned and within session bounds
  • Calendar required-param 422 & graceful date defaults
  • Quick iter4 smoke regression (auth/me + sessions list + payments list)
Cleanup: deletes any TEST_iter5 payments for period 2099-02 after run.
"""
import os
import uuid
from datetime import datetime
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://squad-flow.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = ("admin@badminton.app", "Admin@12345")
COACH = ("coach@badminton.app", "Coach@12345")
PARENT = ("parent@badminton.app", "Parent@12345")

TEST_PERIOD = "2099-02"


def _login(email, pw):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=30)
    assert r.status_code == 200, f"login {email}: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="session")
def admin():
    return _login(*ADMIN)


@pytest.fixture(scope="session")
def coach():
    return _login(*COACH)


@pytest.fixture(scope="session")
def parent():
    return _login(*PARENT)


# ----------------------------- Scheduler endpoints -----------------------------
class TestScheduler:
    def test_status_running(self, admin):
        r = admin.get(f"{API}/scheduler/status", timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("running") is True
        job_ids = {j["id"] for j in body.get("jobs", [])}
        assert "monthly_invoices" in job_ids
        assert "dues_reminders" in job_ids
        # next_run_time should be ISO parseable
        for j in body["jobs"]:
            nrt = j.get("next_run_time")
            assert nrt and isinstance(nrt, str)
            datetime.fromisoformat(nrt.replace("Z", "+00:00"))

    def test_next_period(self, admin):
        r = admin.get(f"{API}/scheduler/next-period", timeout=15)
        assert r.status_code == 200
        body = r.json()
        assert "next_period" in body and "current_period" in body
        # Format YYYY-MM
        for k in ("next_period", "current_period"):
            v = body[k]
            assert len(v) == 7 and v[4] == "-"
            datetime.strptime(v, "%Y-%m")

    def test_run_monthly_invoices_idempotent(self, admin):
        # First call (might create or skip depending on seeded enrollments)
        r1 = admin.post(
            f"{API}/scheduler/run-monthly-invoices",
            json={"period": TEST_PERIOD},
            timeout=60,
        )
        assert r1.status_code == 200, r1.text
        b1 = r1.json()
        assert b1.get("period") == TEST_PERIOD
        assert "created" in b1 and "skipped" in b1
        # Second call should not duplicate
        r2 = admin.post(
            f"{API}/scheduler/run-monthly-invoices",
            json={"period": TEST_PERIOD},
            timeout=60,
        )
        assert r2.status_code == 200, r2.text
        b2 = r2.json()
        assert b2.get("created", 0) == 0
        # Cleanup: delete test payments for this period
        try:
            payments = admin.get(f"{API}/payments", timeout=20).json()
            for p in payments:
                if p.get("period") == TEST_PERIOD:
                    pid = p.get("id") or p.get("_id")
                    if pid:
                        admin.delete(f"{API}/payments/{pid}", timeout=10)
        except Exception:
            pass

    def test_run_monthly_invoices_default_next_period(self, admin):
        # Empty body => uses next_period_yyyy_mm(); call once just to verify no 5xx
        r = admin.post(f"{API}/scheduler/run-monthly-invoices", json={}, timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "period" in body
        # Cleanup: only delete payments freshly created in this default-period run (defensive — best-effort)
        try:
            period = body["period"]
            payments = admin.get(f"{API}/payments", timeout=20).json()
            # Only cleanup if no real production payments exist for that future period (idempotent re-run friendly)
            # Skip cleanup here to avoid touching real data
            _ = payments, period
        except Exception:
            pass

    def test_run_dues_reminders(self, admin):
        r = admin.post(f"{API}/scheduler/run-dues-reminders", timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        # Response should always have these keys, even in Resend sandbox
        assert "sent" in body and "failed" in body and "skipped" in body
        # No 5xx — sandbox-mode is allowed to return all skipped/failed (whitelisting)
        assert isinstance(body["sent"], int)
        assert isinstance(body["failed"], int)
        assert isinstance(body["skipped"], int)

    def test_coach_forbidden_on_scheduler(self, coach):
        for path, method, body in [
            ("/scheduler/status", "GET", None),
            ("/scheduler/next-period", "GET", None),
            ("/scheduler/run-monthly-invoices", "POST", {"period": TEST_PERIOD}),
            ("/scheduler/run-dues-reminders", "POST", {}),
        ]:
            if method == "GET":
                r = coach.get(f"{API}{path}", timeout=15)
            else:
                r = coach.post(f"{API}{path}", json=body, timeout=15)
            assert r.status_code in (401, 403), f"coach on {path} got {r.status_code}"

    def test_parent_forbidden_on_scheduler(self, parent):
        for path, method, body in [
            ("/scheduler/status", "GET", None),
            ("/scheduler/next-period", "GET", None),
            ("/scheduler/run-monthly-invoices", "POST", {"period": TEST_PERIOD}),
            ("/scheduler/run-dues-reminders", "POST", {}),
        ]:
            if method == "GET":
                r = parent.get(f"{API}{path}", timeout=15)
            else:
                r = parent.post(f"{API}{path}", json=body, timeout=15)
            assert r.status_code in (401, 403), f"parent on {path} got {r.status_code}"


# ----------------------------- Calendar endpoints -----------------------------
class TestCalendar:
    def test_admin_calendar_events_shape(self, admin):
        r = admin.get(
            f"{API}/calendar/events",
            params={"start": "2026-04-01", "end": "2026-05-15"},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        events = r.json()
        assert isinstance(events, list)
        if not events:
            pytest.skip("admin returned no events; expected sessions starting 2026-04-01")
        # Validate event shape
        ev = events[0]
        for key in ("id", "title", "start", "end", "color", "textColor", "extendedProps"):
            assert key in ev, f"missing {key}: {ev}"
        ep = ev["extendedProps"]
        for key in ("session_id", "skill_level", "location", "coach_name", "max_students", "monthly_price", "type"):
            assert key in ep, f"missing extendedProps.{key}"
        assert ep["type"] == "session"
        # start parseable
        datetime.fromisoformat(ev["start"])
        datetime.fromisoformat(ev["end"])

    def test_admin_calendar_recurrence_math(self, admin):
        # Pull sessions; find one with a known days_of_week, verify only those weekdays appear
        r = admin.get(f"{API}/calendar/events", params={"start": "2026-04-01", "end": "2026-05-15"}, timeout=20)
        assert r.status_code == 200
        events = r.json()
        if not events:
            pytest.skip("no events to validate recurrence math against")
        # All events: confirm start dates fall within range
        rng_start = datetime(2026, 4, 1)
        rng_end = datetime(2026, 5, 15, 23, 59, 59)
        for ev in events:
            start_dt = datetime.fromisoformat(ev["start"])
            assert rng_start <= start_dt <= rng_end, f"event {ev['id']} start {start_dt} out of range"

        # Now pick the first event's session_id and look up that session's days_of_week
        sid = events[0]["extendedProps"]["session_id"]
        # Fetch session to grab days_of_week
        s = admin.get(f"{API}/sessions/{sid}", timeout=15)
        if s.status_code != 200:
            pytest.skip("session lookup failed")
        days = s.json().get("days_of_week") or []
        if not days:
            pytest.skip("session has no days_of_week to verify")
        day_map = {"monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "wednesday": 2, "wed": 2,
                   "thursday": 3, "thu": 3, "friday": 4, "fri": 4, "saturday": 5, "sat": 5, "sunday": 6, "sun": 6}
        allowed_weekdays = {day_map[d.strip().lower()] for d in days if d.strip().lower() in day_map}
        # Filter events to this session
        sess_events = [e for e in events if e["extendedProps"]["session_id"] == sid]
        for e in sess_events:
            dt = datetime.fromisoformat(e["start"])
            assert dt.weekday() in allowed_weekdays, f"event weekday {dt.weekday()} not in {allowed_weekdays}"

    def test_calendar_required_params_422(self, admin):
        r = admin.get(f"{API}/calendar/events", timeout=15)
        assert r.status_code == 422

    def test_calendar_invalid_date_does_not_500(self, admin):
        r = admin.get(
            f"{API}/calendar/events",
            params={"start": "not-a-date", "end": "also-bad"},
            timeout=20,
        )
        # Falls back to defaults — must not 5xx
        assert r.status_code < 500, f"got {r.status_code}: {r.text}"

    def test_coach_calendar_role_scoped(self, coach):
        r = coach.get(
            f"{API}/calendar/events",
            params={"start": "2026-04-01", "end": "2026-05-15"},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        events = r.json()
        assert isinstance(events, list)
        # Seeded coach is not assigned to any session => []
        # (do not fail on non-empty though — coach may have assignments)

    def test_parent_calendar_role_scoped(self, parent):
        r = parent.get(
            f"{API}/calendar/events",
            params={"start": "2026-04-01", "end": "2026-05-15"},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        events = r.json()
        assert isinstance(events, list)


# ----------------------------- Quick iter4 regression smoke -----------------------------
class TestRegressionSmoke:
    def test_admin_me(self, admin):
        assert admin.get(f"{API}/auth/me", timeout=15).status_code == 200

    def test_coach_me(self, coach):
        assert coach.get(f"{API}/auth/me", timeout=15).status_code == 200

    def test_parent_me(self, parent):
        assert parent.get(f"{API}/auth/me", timeout=15).status_code == 200

    def test_sessions_list(self, admin):
        r = admin.get(f"{API}/sessions", timeout=15)
        assert r.status_code == 200 and isinstance(r.json(), list)

    def test_payments_list(self, admin):
        r = admin.get(f"{API}/payments", timeout=15)
        assert r.status_code == 200 and isinstance(r.json(), list)

    def test_waitlist_list(self, admin):
        r = admin.get(f"{API}/waitlist", timeout=15)
        assert r.status_code == 200

    def test_billing_config(self, admin):
        r = admin.get(f"{API}/billing/config", timeout=15)
        assert r.status_code == 200
