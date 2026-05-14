"""Comprehensive backend integration tests for Badminton Academy Manager.

Covers auth, role-based access, invites, sessions, students, enrollments,
payments, expenses, payout rules, coach payouts, attendance, lesson plans,
progress notes, messages, notifications, dashboards, reports CSV, and audit
logs. Uses public REACT_APP_BACKEND_URL for true end-to-end coverage.
"""
import os
import io
import csv
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path("/app/frontend/.env"))
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN = {"email": "admin@badminton.app", "password": "Admin@12345"}
COACH = {"email": "coach@badminton.app", "password": "Coach@12345"}
PARENT = {"email": "parent@badminton.app", "password": "Parent@12345"}

CURRENT_PERIOD = datetime.now(timezone.utc).strftime("%Y-%m")


def _session_for(creds):
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/login", json=creds, timeout=15)
    assert r.status_code == 200, f"Login failed for {creds['email']}: {r.status_code} {r.text}"
    return s


# -------- shared session-scoped state --------
state: dict = {}


# ============================================================
# 1) Auth + /me + logout + role detection
# ============================================================
class TestAuth:
    def test_admin_login_and_me(self):
        s = _session_for(ADMIN)
        me = s.get(f"{API}/auth/me").json()
        assert me["role"] == "admin"
        assert me["email"] == ADMIN["email"]
        state["admin_session"] = s
        state["admin_id"] = me["id"]

    def test_coach_login_and_me(self):
        s = _session_for(COACH)
        me = s.get(f"{API}/auth/me").json()
        assert me["role"] == "coach"
        state["coach_session"] = s
        state["coach_id"] = me["id"]

    def test_parent_login_and_me(self):
        s = _session_for(PARENT)
        me = s.get(f"{API}/auth/me").json()
        assert me["role"] == "parent"
        state["parent_session"] = s
        state["parent_id"] = me["id"]

    def test_invalid_login(self):
        r = requests.post(f"{API}/auth/login",
                          json={"email": ADMIN["email"], "password": "wrong"}, timeout=10)
        assert r.status_code == 401

    def test_logout_clears_cookies(self):
        s = _session_for(ADMIN)
        r = s.post(f"{API}/auth/logout")
        assert r.status_code == 200
        r2 = s.get(f"{API}/auth/me")
        assert r2.status_code == 401

    def test_parent_register_new(self):
        email = f"test_parent_{uuid.uuid4().hex[:8]}@example.com"
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        r = s.post(f"{API}/auth/register",
                   json={"email": email, "password": "Test@12345", "name": "Test Parent"})
        assert r.status_code == 200
        data = r.json()
        assert data["role"] == "parent"
        state["other_parent_id"] = data["id"]
        state["other_parent_session"] = s
        me = s.get(f"{API}/auth/me").json()
        assert me["email"] == email.lower()


# ============================================================
# 2) Role-based access (403 / 401)
# ============================================================
class TestRBAC:
    def test_parent_cannot_access_expenses(self):
        r = state["parent_session"].get(f"{API}/expenses")
        assert r.status_code == 403

    def test_coach_cannot_access_payments(self):
        r = state["coach_session"].get(f"{API}/payments")
        assert r.status_code == 403

    def test_anonymous_blocked_from_admin_dashboard(self):
        r = requests.get(f"{API}/dashboard/admin", timeout=10)
        assert r.status_code == 401


# ============================================================
# 3) Invites flow
# ============================================================
class TestInvites:
    def test_admin_creates_invite(self):
        email = f"test_coach_{uuid.uuid4().hex[:6]}@example.com"
        r = state["admin_session"].post(f"{API}/invites",
                                        json={"email": email, "role": "coach", "name": "Inv Coach"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["role"] == "coach" and "token" in data
        state["invite_token"] = data["token"]
        state["invite_email"] = email.lower()

    def test_list_invites(self):
        r = state["admin_session"].get(f"{API}/invites")
        assert r.status_code == 200
        assert any(i.get("email") == state["invite_email"] for i in r.json()), \
            f"invite {state['invite_email']} not found in {[i.get('email') for i in r.json()]}"

    def test_accept_invite(self):
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        r = s.post(f"{API}/invites/accept/{state['invite_token']}",
                   json={"password": "NewPass@123", "name": "Invited Coach"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["role"] == "coach"
        state["other_coach_id"] = data["id"]
        state["other_coach_session"] = s


# ============================================================
# 4) Sessions CRUD (admin)
# ============================================================
class TestSessions:
    def test_create_session(self):
        body = {
            "name": "TEST Session Beginners",
            "skill_level": "beginner",
            "age_group": "8-12",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "days_of_week": ["Mon", "Wed", "Fri"],
            "start_time": "16:00",
            "end_time": "17:00",
            "location": "Court 1",
            "max_students": 10,
            "monthly_price": 100.0,
            "coach_id": state["coach_id"],
            "status": "active",
        }
        r = state["admin_session"].post(f"{API}/sessions", json=body)
        assert r.status_code == 200, r.text
        sid = r.json()["id"]
        state["session_id"] = sid

    def test_session_appears_in_list(self):
        r = state["admin_session"].get(f"{API}/sessions")
        assert r.status_code == 200
        assert any(s["id"] == state["session_id"] for s in r.json())

    def test_patch_session(self):
        body = {
            "name": "TEST Session Renamed",
            "skill_level": "beginner",
            "age_group": "8-12",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "days_of_week": ["Mon", "Wed", "Fri"],
            "start_time": "16:00",
            "end_time": "17:00",
            "location": "Court 1",
            "max_students": 10,
            "monthly_price": 100.0,
            "coach_id": state["coach_id"],
            "status": "active",
        }
        r = state["admin_session"].patch(f"{API}/sessions/{state['session_id']}", json=body)
        assert r.status_code == 200

    def test_coach_sees_only_own_sessions(self):
        r = state["coach_session"].get(f"{API}/sessions")
        assert r.status_code == 200
        for s in r.json():
            assert s.get("coach_id") == state["coach_id"]

    def test_create_second_coach_session(self):
        body = {
            "name": "TEST Other Coach Session",
            "skill_level": "beginner",
            "age_group": "8-12",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "days_of_week": ["Tue"],
            "start_time": "18:00",
            "end_time": "19:00",
            "location": "Court 2",
            "max_students": 10,
            "monthly_price": 100.0,
            "coach_id": state["other_coach_id"],
            "status": "active",
        }
        r = state["admin_session"].post(f"{API}/sessions", json=body)
        assert r.status_code == 200, r.text
        state["other_session_id"] = r.json()["id"]


# ============================================================
# 5) Students + Enrollments (parent flow)
# ============================================================
class TestParentFlow:
    def test_parent_creates_child(self):
        body = {
            "first_name": "TEST",
            "last_name": "Child",
            "dob": "2015-05-01",
            "skill_level": "beginner",
            "emergency_contact_name": "Mom",
            "emergency_contact_phone": "555-1111",
            "waiver_accepted": True,
        }
        r = state["parent_session"].post(f"{API}/students", json=body)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["parent_user_id"] == state["parent_id"]
        state["student_id"] = data["id"]

    def test_parent_lists_own_children(self):
        r = state["parent_session"].get(f"{API}/students")
        assert r.status_code == 200
        assert any(s["id"] == state["student_id"] for s in r.json())

    def test_parent_enrolls_child(self):
        body = {"student_id": state["student_id"], "session_id": state["session_id"]}
        r = state["parent_session"].post(f"{API}/enrollments", json=body)
        assert r.status_code == 200, r.text
        state["enrollment_id"] = r.json()["id"]
        approve = state["admin_session"].post(f"{API}/enrollments/{state['enrollment_id']}/approve")
        assert approve.status_code == 200, approve.text

    def test_capacity_check(self):
        # try to enroll same student again -> Already enrolled
        body = {"student_id": state["student_id"], "session_id": state["session_id"]}
        r = state["parent_session"].post(f"{API}/enrollments", json=body)
        assert r.status_code == 400

    def test_admin_creates_other_student_and_enrollment(self):
        body = {
            "first_name": "TEST",
            "last_name": "OtherChild",
            "dob": "2016-05-01",
            "skill_level": "beginner",
            "emergency_contact_name": "Admin",
            "emergency_contact_phone": "555-2222",
            "waiver_accepted": True,
        }
        r = state["admin_session"].post(f"{API}/students", json=body)
        assert r.status_code == 200, r.text
        state["other_student_id"] = r.json()["id"]

        er = state["admin_session"].post(
            f"{API}/enrollments",
            json={"student_id": state["other_student_id"], "session_id": state["other_session_id"]},
        )
        assert er.status_code == 200, er.text
        state["other_enrollment_id"] = er.json()["id"]


class TestAuthorizationBoundaries:
    def test_coach_cannot_filter_students_by_another_coachs_session(self):
        r = state["coach_session"].get(f"{API}/students", params={"session_id": state["other_session_id"]})
        assert r.status_code == 403

    def test_coach_cannot_filter_enrollments_by_another_coachs_session(self):
        r = state["coach_session"].get(f"{API}/enrollments", params={"session_id": state["other_session_id"]})
        assert r.status_code == 403

    def test_coach_cannot_filter_attendance_by_another_coachs_session(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        body = {
            "session_id": state["other_session_id"],
            "date": today,
            "items": [{"student_id": state["other_student_id"], "status": "present"}],
        }
        admin_mark = state["admin_session"].post(f"{API}/attendance/bulk", json=body)
        assert admin_mark.status_code == 200, admin_mark.text

        r = state["coach_session"].get(f"{API}/attendance", params={"session_id": state["other_session_id"]})
        assert r.status_code == 403

    def test_coach_cannot_create_progress_note_for_unassigned_student(self):
        body = {
            "student_id": state["other_student_id"],
            "session_id": state["other_session_id"],
            "note": "TEST unauthorized note",
        }
        r = state["coach_session"].post(f"{API}/progress-notes", json=body)
        assert r.status_code == 403

    def test_coach_cannot_filter_progress_notes_by_unassigned_student(self):
        body = {
            "student_id": state["other_student_id"],
            "session_id": state["other_session_id"],
            "note": "TEST authorized other coach note",
        }
        created = state["other_coach_session"].post(f"{API}/progress-notes", json=body)
        assert created.status_code == 200, created.text

        r = state["coach_session"].get(f"{API}/progress-notes", params={"student_id": state["other_student_id"]})
        assert r.status_code == 403

    def test_parent_cannot_message_arbitrary_parent(self):
        r = state["parent_session"].post(
            f"{API}/messages",
            json={"to_user_id": state["other_parent_id"], "body": "TEST unauthorized parent message"},
        )
        assert r.status_code == 403


# ============================================================
# 6) Payments: generate monthly, list, discount, mark paid
# ============================================================
class TestPayments:
    def test_generate_monthly(self):
        r = state["admin_session"].post(f"{API}/payments/generate-monthly",
                                        json={"period": CURRENT_PERIOD})
        assert r.status_code == 200, r.text
        # at least 0 created (idempotent ok)
        assert "created" in r.json()

    def test_list_pending_payments(self):
        r = state["admin_session"].get(f"{API}/payments", params={"status": "pending"})
        assert r.status_code == 200
        pays = [p for p in r.json() if p["enrollment_id"] == state["enrollment_id"]]
        assert pays, "Expected pending payment for the new enrollment"
        state["payment_id"] = pays[0]["id"]
        state["payment_session_id"] = pays[0]["session_id"]

    def test_apply_discount(self):
        r = state["admin_session"].patch(
            f"{API}/payments/{state['payment_id']}/apply-discount",
            json={"discount": 10})
        assert r.status_code == 200

    def test_mark_paid(self):
        r = state["admin_session"].patch(
            f"{API}/payments/{state['payment_id']}/mark-paid",
            json={"payment_method": "cash"})
        assert r.status_code == 200
        # verify status persisted
        r2 = state["admin_session"].get(f"{API}/payments", params={"status": "paid"})
        assert any(p["id"] == state["payment_id"] for p in r2.json())


# ============================================================
# 7) Expenses
# ============================================================
class TestExpenses:
    def test_create_and_list(self):
        body = {"category": "Equipment", "description": "TEST shuttles",
                "amount": 50.0, "date": f"{CURRENT_PERIOD}-15", "paid_to": "Vendor",
                "status": "paid"}
        r = state["admin_session"].post(f"{API}/expenses", json=body)
        assert r.status_code == 200
        eid = r.json()["id"]
        state["expense_id"] = eid
        r2 = state["admin_session"].get(f"{API}/expenses")
        assert any(e["id"] == eid for e in r2.json())

    def test_delete_expense(self):
        r = state["admin_session"].delete(f"{API}/expenses/{state['expense_id']}")
        assert r.status_code == 200


# ============================================================
# 8) Payout rules + coach payouts (calculate -> approve -> pay)
# ============================================================
class TestPayouts:
    def test_create_payout_rule(self):
        r = state["admin_session"].post(f"{API}/payout-rules", json={
            "coach_id": state["coach_id"],
            "rule_type": "revenue_percentage",
            "value": 30,
        })
        assert r.status_code == 200

    def test_calculate_payouts(self):
        # Clear stale payout for this coach+period to ensure recalculation
        from pymongo import MongoClient
        mc = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        mc[os.environ.get("DB_NAME", "test_database")].coach_payouts.delete_many(
            {"coach_id": state["coach_id"], "period": CURRENT_PERIOD})
        r = state["admin_session"].post(f"{API}/coach-payouts/calculate",
                                        json={"period": CURRENT_PERIOD})
        assert r.status_code == 200
        r2 = state["admin_session"].get(f"{API}/coach-payouts",
                                        params={"period": CURRENT_PERIOD})
        assert r2.status_code == 200
        ours = [p for p in r2.json() if p["coach_id"] == state["coach_id"]]
        assert ours, "Expected payout calculated for coach"
        state["payout_id"] = ours[0]["id"]
        # revenue was 90 (100 - 10 discount), 30% = 27
        assert ours[0]["calculated_amount"] == 27.0, f"Got {ours[0]['calculated_amount']}"

    def test_approve_payout(self):
        r = state["admin_session"].post(
            f"{API}/coach-payouts/{state['payout_id']}/approve")
        assert r.status_code == 200

    def test_mark_payout_paid(self):
        r = state["admin_session"].post(
            f"{API}/coach-payouts/{state['payout_id']}/mark-paid")
        assert r.status_code == 200

    def test_cannot_approve_paid(self):
        r = state["admin_session"].post(
            f"{API}/coach-payouts/{state['payout_id']}/approve")
        assert r.status_code == 400


# ============================================================
# 9) Attendance (coach + parent scope)
# ============================================================
class TestAttendance:
    def test_coach_bulk_attendance(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        body = {
            "session_id": state["session_id"],
            "date": today,
            "items": [{"student_id": state["student_id"], "status": "present"}],
        }
        r = state["coach_session"].post(f"{API}/attendance/bulk", json=body)
        assert r.status_code == 200, r.text
        state["attendance_date"] = today

    def test_parent_sees_only_own_attendance(self):
        r = state["parent_session"].get(f"{API}/attendance")
        assert r.status_code == 200
        # Get all student ids that belong to this parent
        my_students = state["parent_session"].get(f"{API}/students").json()
        my_sids = {s["id"] for s in my_students}
        for a in r.json():
            assert a["student_id"] in my_sids, \
                f"attendance for non-own student {a['student_id']} leaked"


# ============================================================
# 10) Lesson plans
# ============================================================
class TestLessonPlans:
    def test_coach_creates_lesson_plan(self):
        body = {
            "session_id": state["session_id"],
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "objective": "TEST footwork drills",
        }
        r = state["coach_session"].post(f"{API}/lesson-plans", json=body)
        assert r.status_code == 200

    def test_coach_lists_lesson_plans(self):
        r = state["coach_session"].get(f"{API}/lesson-plans")
        assert r.status_code == 200
        assert len(r.json()) >= 1


# ============================================================
# 11) Progress notes
# ============================================================
class TestProgressNotes:
    def test_coach_creates_progress_note(self):
        body = {"student_id": state["student_id"],
                "session_id": state["session_id"],
                "note": "TEST: great improvement on backhand"}
        r = state["coach_session"].post(f"{API}/progress-notes", json=body)
        assert r.status_code == 200

    def test_parent_sees_own_child_notes(self):
        r = state["parent_session"].get(f"{API}/progress-notes")
        assert r.status_code == 200
        assert any(n["student_id"] == state["student_id"] for n in r.json())


# ============================================================
# 12) Messages + notifications
# ============================================================
class TestMessaging:
    def test_send_message_admin_to_parent(self):
        r = state["admin_session"].post(f"{API}/messages",
                                        json={"to_user_id": state["parent_id"],
                                              "body": "TEST: hello parent"})
        assert r.status_code == 200

    def test_parent_threads(self):
        r = state["parent_session"].get(f"{API}/messages/threads")
        assert r.status_code == 200
        assert any(t["other_user_id"] == state["admin_id"] for t in r.json())

    def test_parent_thread_marks_read(self):
        r = state["parent_session"].get(f"{API}/messages/thread/{state['admin_id']}")
        assert r.status_code == 200
        assert len(r.json()) >= 1

    def test_parent_notifications(self):
        r = state["parent_session"].get(f"{API}/notifications")
        assert r.status_code == 200
        notifs = r.json()
        assert any(n["type"] == "message" for n in notifs)
        state["notif_id"] = notifs[0]["id"]

    def test_mark_one_read(self):
        r = state["parent_session"].patch(
            f"{API}/notifications/{state['notif_id']}/read")
        assert r.status_code == 200

    def test_mark_all_read(self):
        r = state["parent_session"].post(f"{API}/notifications/read-all")
        assert r.status_code == 200


# ============================================================
# 13) Dashboards
# ============================================================
class TestDashboards:
    def test_admin_dashboard_kpis(self):
        r = state["admin_session"].get(f"{API}/dashboard/admin")
        assert r.status_code == 200
        d = r.json()
        for key in ["monthly_income", "expenses", "coach_payouts", "net_profit"]:
            assert key in d["kpis"]
        assert "trend" in d and isinstance(d["trend"], list)
        assert "upcoming" in d
        assert "session_profitability" in d

    def test_coach_dashboard(self):
        r = state["coach_session"].get(f"{API}/dashboard/coach")
        assert r.status_code == 200
        assert "kpis" in r.json()

    def test_parent_dashboard(self):
        r = state["parent_session"].get(f"{API}/dashboard/parent")
        assert r.status_code == 200
        assert "kpis" in r.json()
        assert r.json()["kpis"]["children"] >= 1


# ============================================================
# 14) Reports CSV
# ============================================================
class TestReports:
    @pytest.mark.parametrize("endpoint", [
        "revenue.csv", "profit.csv", "pending-payments.csv",
        "attendance.csv", "coach-payouts.csv",
    ])
    def test_admin_csv(self, endpoint):
        r = state["admin_session"].get(f"{API}/reports/{endpoint}")
        assert r.status_code == 200, f"{endpoint}: {r.status_code}"
        assert "text/csv" in r.headers.get("content-type", "")
        # parse to ensure valid csv
        rows = list(csv.reader(io.StringIO(r.text)))
        assert len(rows) >= 1  # at least header

    def test_parent_cannot_access_reports(self):
        r = state["parent_session"].get(f"{API}/reports/revenue.csv")
        assert r.status_code == 403


# ============================================================
# 15) Audit logs
# ============================================================
class TestAuditLogs:
    def test_admin_audit_logs(self):
        r = state["admin_session"].get(f"{API}/audit-logs")
        assert r.status_code == 200
        logs = r.json()
        assert len(logs) >= 1
        # Should contain action types we ran
        actions = {log["action"] for log in logs}
        assert "create" in actions or "mark_paid" in actions

    def test_non_admin_blocked(self):
        r = state["coach_session"].get(f"{API}/audit-logs")
        assert r.status_code == 403


# ============================================================
# 16) Soft delete session at end
# ============================================================
class TestCleanup:
    def test_soft_delete_session(self):
        r = state["admin_session"].delete(f"{API}/sessions/{state['session_id']}")
        assert r.status_code == 200
        r2 = state["admin_session"].get(f"{API}/sessions")
        assert not any(s["id"] == state["session_id"] for s in r2.json())
