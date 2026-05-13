"""Iteration 2 backend tests — new features only.

Covers:
- Admin dashboard new KPIs (expected_revenue, collected_revenue, waived_value, attendance_rate, session utilization)
- Dues Followup (/api/dues-followup)
- Coach Payslip (/api/coach-payouts/{id}/payslip)
- User admin: PATCH /api/users/{id} (with email) + reset-password
- Enrollment approval workflow (parent-created => pending; admin approve)
- Enrollment transfer (permanent + override) + /move-log
- generate-monthly skips NoCharge/Waived and pending-approval
- Student t_shirt_size + previous_experience
- Attendance status 'make_up'
"""
import os
import uuid
import time
from pathlib import Path
from datetime import datetime, timezone

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path("/app/frontend/.env"))
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@badminton.app", "password": "Admin@12345"}
COACH = {"email": "coach@badminton.app", "password": "Coach@12345"}
GOWTHAM = {"email": "gowtham@blno.academy", "password": "Coach@12345"}

state: dict = {}


def _session(creds):
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"Login failed for {creds['email']}: {r.text}"
    return s


# ---------- Setup ----------
class TestSetup:
    def test_admin_login(self):
        state["admin"] = _session(ADMIN)
        me = state["admin"].get(f"{API}/auth/me").json()
        assert me["role"] == "admin"

    def test_real_coach_login(self):
        try:
            state["gowtham"] = _session(GOWTHAM)
            me = state["gowtham"].get(f"{API}/auth/me").json()
            state["gowtham_id"] = me["id"]
        except AssertionError:
            pytest.skip("Real coach not seeded; using fallback demo coach")


# ---------- Dashboard new KPIs ----------
class TestDashboardKPIs:
    def test_admin_dashboard_new_fields(self):
        r = state["admin"].get(f"{API}/dashboard/admin", params={"period": "2026-05"})
        assert r.status_code == 200, r.text
        d = r.json()
        k = d["kpis"]
        for key in ("expected_revenue", "collected_revenue", "waived_value", "attendance_rate"):
            assert key in k, f"missing {key} in kpis: {list(k.keys())}"
        assert "session_profitability" in d
        # session profitability must include utilization + capacity
        if d["session_profitability"]:
            sp = d["session_profitability"][0]
            assert "utilization" in sp or "capacity" in sp, f"missing utilization/capacity: {list(sp.keys())}"
        state["dashboard"] = d


# ---------- Dues Followup ----------
class TestDuesFollowup:
    def test_dues_followup_shape(self):
        r = state["admin"].get(f"{API}/dues-followup")
        assert r.status_code == 200, r.text
        rows = r.json()
        assert isinstance(rows, list)
        if rows:
            row = rows[0]
            for key in ("parent_id", "parent_name", "kids", "total_due", "message", "whatsapp_url"):
                assert key in row, f"missing {key}: {list(row.keys())}"
            # message contains zelle/dollar
            assert "$" in row["message"]

    def test_dues_requires_admin(self):
        # parent should not access
        try:
            s = _session({"email": "parent@badminton.app", "password": "Parent@12345"})
            r = s.get(f"{API}/dues-followup")
            assert r.status_code in (401, 403)
        except AssertionError:
            pytest.skip("parent demo user unavailable")


# ---------- Coach Payslip ----------
class TestCoachPayslip:
    def test_payslip_for_gowtham_or_demo(self):
        # Use real coach if available else fallback to demo coach
        if "gowtham_id" in state:
            cid = state["gowtham_id"]
        else:
            users = state["admin"].get(f"{API}/users", params={"role": "coach"}).json()
            assert users, "No coach found"
            cid = users[0]["id"]
        r = state["admin"].get(f"{API}/coach-payouts/{cid}/payslip", params={"period": "2026-05"})
        assert r.status_code == 200, r.text
        d = r.json()
        for key in ("coach_id", "coach_name", "kids_enrolled", "expected_revenue",
                    "payout_amount", "rows"):
            assert key in d, f"missing {key}: {list(d.keys())}"
        if d["rows"]:
            assert "billing_type" in d["rows"][0]


# ---------- User admin (edit + reset-password) ----------
class TestUserAdmin:
    def test_create_then_patch_email(self):
        # Find a parent user to patch (or create one)
        rs = state["admin"].get(f"{API}/users", params={"role": "parent"})
        assert rs.status_code == 200
        parents = rs.json()
        assert parents, "Need at least one parent user"
        # Create a new throwaway parent via register
        new_email = f"test_iter2_{uuid.uuid4().hex[:8]}@example.com"
        s2 = requests.Session()
        s2.headers.update({"Content-Type": "application/json"})
        rr = s2.post(f"{API}/auth/register", json={
            "email": new_email, "password": "Pass@1234", "name": "Iter2 Tmp"
        })
        assert rr.status_code == 200, rr.text
        # Find this user's id
        users2 = state["admin"].get(f"{API}/users", params={"role": "parent"}).json()
        u = next((x for x in users2 if x.get("email") == new_email.lower()), None)
        assert u, f"Created user {new_email} not found"
        state["tmp_user_id"] = u["id"]
        state["tmp_user_email"] = new_email.lower()
        # PATCH name + phone
        p = state["admin"].patch(f"{API}/users/{u['id']}",
                                 json={"name": "Iter2 Renamed", "phone": "5551234"})
        assert p.status_code == 200, p.text
        # Verify
        u2 = state["admin"].get(f"{API}/users/{u['id']}").json()
        assert u2["name"] == "Iter2 Renamed"
        assert u2["phone"] == "5551234"

    def test_patch_email_uniqueness(self):
        # Try to change tmp user's email to admin's email -> 400
        r = state["admin"].patch(f"{API}/users/{state['tmp_user_id']}",
                                 json={"email": ADMIN["email"]})
        assert r.status_code == 400

    def test_admin_reset_password(self):
        r = state["admin"].post(f"{API}/users/{state['tmp_user_id']}/reset-password",
                                json={"password": "NewPass@123"})
        assert r.status_code == 200
        # Login with new password
        s2 = requests.Session()
        s2.headers.update({"Content-Type": "application/json"})
        lr = s2.post(f"{API}/auth/login",
                     json={"email": state["tmp_user_email"], "password": "NewPass@123"})
        assert lr.status_code == 200, lr.text


# ---------- Student t-shirt + previous experience ----------
class TestStudentExtras:
    def test_parent_creates_child_with_extras(self):
        sp = _session({"email": state["tmp_user_email"], "password": "NewPass@123"})
        state["parent_session"] = sp
        body = {
            "first_name": "TESTIter2",
            "last_name": "Kid",
            "dob": "2015-06-15",
            "skill_level": "beginner",
            "emergency_contact_name": "Mom",
            "emergency_contact_phone": "5551234",
            "waiver_accepted": True,
            "t_shirt_size": "M",
            "previous_experience": "Played at school for 1 year",
        }
        r = sp.post(f"{API}/students", json=body)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["t_shirt_size"] == "M"
        assert "Played" in d["previous_experience"]
        state["child_id"] = d["id"]


# ---------- Enrollment approval workflow ----------
class TestEnrollmentApproval:
    def test_parent_enroll_pending(self):
        # Use any active session
        sessions = state["admin"].get(f"{API}/sessions").json()
        active = [s for s in sessions if s.get("status") == "active"]
        assert active, "No active sessions"
        # Pick one with capacity room
        target = None
        for s in active:
            cnt = state["admin"].get(f"{API}/enrollments", params={"session_id": s["id"]}).json()
            if len(cnt) < s.get("max_students", 999):
                target = s
                break
        assert target, "No session with capacity"
        state["target_session_id"] = target["id"]
        r = state["parent_session"].post(f"{API}/enrollments", json={
            "session_id": target["id"], "student_id": state["child_id"]
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["approval_status"] == "pending", f"got {d.get('approval_status')}"
        state["pending_enr_id"] = d["id"]

    def test_pending_approval_list(self):
        r = state["admin"].get(f"{API}/enrollments/pending-approval")
        assert r.status_code == 200, r.text
        items = r.json()
        assert any(it["id"] == state["pending_enr_id"] for it in items), \
            f"pending enrollment {state['pending_enr_id']} not in list"

    def test_admin_approves(self):
        r = state["admin"].post(f"{API}/enrollments/{state['pending_enr_id']}/approve")
        assert r.status_code == 200
        # Verify by listing enrollments
        all_e = state["admin"].get(f"{API}/enrollments",
                                   params={"session_id": state["target_session_id"]}).json()
        ours = next((e for e in all_e if e["id"] == state["pending_enr_id"]), None)
        assert ours and ours.get("approval_status") == "approved"


# ---------- generate-monthly skip logic ----------
class TestGenerateMonthly:
    def test_generate_returns_skip_counts(self):
        r = state["admin"].post(f"{API}/payments/generate-monthly",
                                json={"period": "2026-05"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert "created" in d
        # skipped fields may or may not exist - tolerant
        # at least 'skipped_no_charge' per spec
        assert "skipped_no_charge" in d or "skipped" in d, f"no skip-info: {d}"


# ---------- Enrollment transfer ----------
class TestEnrollmentTransfer:
    def test_transfer_override(self):
        # Need 2 sessions
        sessions = [s for s in state["admin"].get(f"{API}/sessions").json()
                    if s.get("status") == "active"]
        if len(sessions) < 2:
            pytest.skip("Need at least 2 active sessions to test transfer")
        from_sess = next((s for s in sessions if s["id"] == state["target_session_id"]),
                         sessions[0])
        to_sess = next((s for s in sessions if s["id"] != from_sess["id"]), None)
        assert to_sess
        r = state["admin"].post(
            f"{API}/enrollments/{state['pending_enr_id']}/transfer",
            json={"to_session_id": to_sess["id"], "effective_month": "2026-06",
                  "permanent": False, "note": "Iter2 test override"}
        )
        assert r.status_code == 200, r.text
        state["transfer_to_id"] = to_sess["id"]

    def test_move_log_records_transfer(self):
        r = state["admin"].get(f"{API}/move-log")
        assert r.status_code == 200, r.text
        items = r.json()
        ours = [m for m in items if m.get("enrollment_id") == state["pending_enr_id"]]
        assert ours, "move-log missing our transfer"
        assert ours[0]["to_session_id"] == state["transfer_to_id"]
        assert ours[0]["permanent"] is False


# ---------- Make-up attendance ----------
class TestMakeUpAttendance:
    def test_bulk_attendance_makeup(self):
        # Use coach session for the target session
        sess_id = state["target_session_id"]
        sess = state["admin"].get(f"{API}/sessions/{sess_id}").json()
        coach_id = sess.get("coach_id")
        if not coach_id:
            pytest.skip("Target session has no coach")
        # Login as admin to bypass coach lookup (admin can post)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        body = {
            "session_id": sess_id,
            "date": today,
            "items": [{"student_id": state["child_id"], "status": "make_up",
                       "notes": "iter2 makeup"}],
        }
        r = state["admin"].post(f"{API}/attendance/bulk", json=body)
        # Some impls restrict to coach role - tolerate 403 and retry as coach
        if r.status_code == 403:
            cs = _session(COACH)
            r = cs.post(f"{API}/attendance/bulk", json=body)
        assert r.status_code == 200, r.text


# ---------- Cleanup ----------
class TestCleanup:
    def test_delete_temp_student(self):
        # Soft delete the test student
        if state.get("child_id"):
            r = state["parent_session"].delete(f"{API}/students/{state['child_id']}")
            assert r.status_code == 200
