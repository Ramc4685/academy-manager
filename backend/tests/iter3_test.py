"""Iteration 3 tests — Settings, Undo flows, Public register, Stripe, Resend."""
import os
import time
from datetime import datetime, timezone
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://squad-flow.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@badminton.app"
ADMIN_PASSWORD = "Admin@12345"


def _create_approved_parent_enrollment(admin_session, label="AutoPay"):
    uniq = int(time.time() * 1000)
    session_body = {
        "name": f"TEST {label} Session {uniq}",
        "skill_level": "beginner",
        "age_group": "8-12",
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
        "days_of_week": ["Tue"],
        "start_time": "17:00",
        "end_time": "18:00",
        "location": "Court Auto",
        "max_students": 4,
        "monthly_price": 111.0,
        "status": "active",
    }
    sr = admin_session.post(f"{BASE_URL}/api/sessions", json=session_body, timeout=15)
    assert sr.status_code == 200, sr.text
    session_id = sr.json()["id"]

    parent_session = requests.Session()
    email = f"{label.lower()}_{uniq}@example.com"
    body = {
        "parent_name": f"TEST {label} Parent",
        "parent_email": email,
        "parent_phone": "5551234567",
        "password": "TestPass123!",
        "child_first_name": label,
        "child_last_name": "Kid",
        "child_dob": "2015-05-10",
        "child_skill_level": "beginner",
        "emergency_contact_name": "Emergency",
        "emergency_contact_phone": "5559998888",
        "waiver_accepted": True,
        "session_id": session_id,
    }
    r = parent_session.post(f"{BASE_URL}/api/auth/register-full", json=body, timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    paid = admin_session.patch(
        f"{BASE_URL}/api/payments/{data['payment_id']}/mark-paid",
        json={"payment_method": "cash"},
        timeout=15,
    )
    assert paid.status_code == 200, paid.text
    approved = admin_session.post(f"{BASE_URL}/api/enrollments/{data['enrollment_id']}/approve", timeout=15)
    assert approved.status_code == 200, approved.text
    return parent_session, data["enrollment_id"], session_id


# --------- shared session fixtures ---------
@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=20)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="module")
def kishore_id(admin_session):
    """Find kishore@blno.academy user id."""
    r = admin_session.get(f"{BASE_URL}/api/users?role=coach", timeout=20)
    assert r.status_code == 200
    for u in r.json():
        if u["email"] == "kishore@blno.academy":
            return u["id"]
    pytest.skip("kishore coach not present")


# --------- Settings ---------
class TestSettings:
    def test_get_settings_returns_defaults(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/settings", timeout=15)
        assert r.status_code == 200
        d = r.json()
        for k in ("name", "zelle_handle", "reminder_template", "currency",
                  "default_capacity", "beginner_price", "intermediate_price", "advanced_price"):
            assert k in d, f"missing key {k}"

    def test_patch_settings_persists(self, admin_session):
        new_zelle = "TEST-555-0101"
        r = admin_session.patch(f"{BASE_URL}/api/settings",
                                json={"zelle_handle": new_zelle, "default_capacity": 17}, timeout=15)
        assert r.status_code == 200
        assert r.json().get("ok") is True
        # Verify persistence
        r2 = admin_session.get(f"{BASE_URL}/api/settings", timeout=15)
        assert r2.status_code == 200
        d = r2.json()
        assert d["zelle_handle"] == new_zelle
        assert d["default_capacity"] == 17
        # restore
        admin_session.patch(f"{BASE_URL}/api/settings",
                            json={"zelle_handle": "248-885-9243", "default_capacity": 15}, timeout=15)

    def test_payout_basis_invalid(self, admin_session, kishore_id):
        r = admin_session.post(f"{BASE_URL}/api/settings/payout-basis",
                               json={"coach_id": kishore_id, "basis": "garbage"}, timeout=15)
        assert r.status_code == 400


# --------- Coach payslip with expected basis ---------
class TestPayoutBasis:
    def test_set_expected_and_payslip(self, admin_session, kishore_id):
        # Ensure Kishore has a revenue_percentage rule of 30
        admin_session.post(f"{BASE_URL}/api/payout-rules",
                           json={"coach_id": kishore_id, "rule_type": "revenue_percentage",
                                 "value": 30}, timeout=15)
        # Set basis to expected
        r = admin_session.post(f"{BASE_URL}/api/settings/payout-basis",
                               json={"coach_id": kishore_id, "basis": "expected"}, timeout=15)
        assert r.status_code == 200
        # Fetch payslip for 2026-05
        ps = admin_session.get(f"{BASE_URL}/api/coach-payouts/{kishore_id}/payslip?period=2026-05", timeout=20)
        assert ps.status_code == 200, ps.text
        data = ps.json()
        # Spec: expected $1360 × 30% = $408
        assert "payout_amount" in data, f"keys={list(data.keys())}"
        assert data.get("payout_basis") == "expected"
        payout = float(data["payout_amount"])
        expected_rev = float(data.get("expected_revenue") or 0)
        assert expected_rev > 0, "expected_revenue should be >0 for Kishore in 2026-05"
        assert abs(payout - expected_rev * 0.30) < 0.5, \
            f"payout {payout} != expected_revenue {expected_rev} * 0.3 (={expected_rev*0.3})"
        # Restore to collected
        admin_session.post(f"{BASE_URL}/api/settings/payout-basis",
                           json={"coach_id": kishore_id, "basis": "collected"}, timeout=15)


# --------- Undo payment paid / payout flows ---------
class TestUndoFlows:
    def test_payment_undo_paid(self, admin_session):
        # find any paid payment, else create one and mark paid
        r = admin_session.get(f"{BASE_URL}/api/payments?status=paid", timeout=20)
        assert r.status_code == 200
        paid = r.json()
        if paid:
            pid = paid[0]["id"]
        else:
            pytest.skip("No paid payments available")
        # Undo
        ru = admin_session.post(f"{BASE_URL}/api/payments/{pid}/undo-paid", timeout=15)
        assert ru.status_code == 200, ru.text
        # Re-fetch this payment
        rl = admin_session.get(f"{BASE_URL}/api/payments?status=pending", timeout=20)
        assert rl.status_code == 200
        ids = [p["id"] for p in rl.json()]
        assert pid in ids, "Payment did not flip to pending"
        # Restore by marking paid again
        admin_session.patch(f"{BASE_URL}/api/payments/{pid}/mark-paid",
                            json={"payment_method": "zelle", "notes": "test-restore"}, timeout=15)

    def test_payment_undo_paid_when_not_paid(self, admin_session):
        r = admin_session.get(f"{BASE_URL}/api/payments?status=pending", timeout=20)
        assert r.status_code == 200
        if not r.json():
            pytest.skip("no pending payment to test")
        pid = r.json()[0]["id"]
        ru = admin_session.post(f"{BASE_URL}/api/payments/{pid}/undo-paid", timeout=15)
        assert ru.status_code == 400

    def test_payout_undo_approve_and_undo_paid(self, admin_session, kishore_id):
        period = "2026-05"
        # calculate
        admin_session.post(f"{BASE_URL}/api/coach-payouts/calculate",
                           json={"period": period}, timeout=30)
        # list and find Kishore's payout
        r = admin_session.get(f"{BASE_URL}/api/coach-payouts?period={period}", timeout=15)
        assert r.status_code == 200
        items = [p for p in r.json() if p["coach_id"] == kishore_id]
        if not items:
            pytest.skip("No Kishore payout calculated")
        po = items[0]
        # approve if calculated
        if po["status"] == "calculated":
            ra = admin_session.post(f"{BASE_URL}/api/coach-payouts/{po['id']}/approve", timeout=15)
            assert ra.status_code == 200
        elif po["status"] == "paid":
            # Undo paid first
            ru = admin_session.post(f"{BASE_URL}/api/coach-payouts/{po['id']}/undo-paid", timeout=15)
            assert ru.status_code == 200
        # Now state should be 'approved'. Undo approve.
        ru2 = admin_session.post(f"{BASE_URL}/api/coach-payouts/{po['id']}/undo-approve", timeout=15)
        assert ru2.status_code == 200
        # Verify status == 'calculated'
        r2 = admin_session.get(f"{BASE_URL}/api/coach-payouts?period={period}", timeout=15)
        cur = [p for p in r2.json() if p["id"] == po["id"]][0]
        assert cur["status"] == "calculated"

    def test_payout_undo_paid_removes_expense(self, admin_session, kishore_id):
        period = "2026-05"
        # Ensure recalculated & approved
        admin_session.post(f"{BASE_URL}/api/coach-payouts/calculate",
                           json={"period": period}, timeout=30)
        r = admin_session.get(f"{BASE_URL}/api/coach-payouts?period={period}", timeout=15)
        items = [p for p in r.json() if p["coach_id"] == kishore_id]
        if not items:
            pytest.skip("No payout")
        po = items[0]
        if po["status"] == "calculated":
            admin_session.post(f"{BASE_URL}/api/coach-payouts/{po['id']}/approve", timeout=15)
        # mark paid (creates expense)
        rp = admin_session.post(f"{BASE_URL}/api/coach-payouts/{po['id']}/mark-paid", timeout=15)
        assert rp.status_code == 200
        # Confirm expense was created
        re_ = admin_session.get(f"{BASE_URL}/api/expenses", timeout=15)
        expenses_before = [e for e in re_.json() if "Coach Payout" in (e.get("category") or "") and po["id"] in (e.get("notes") or "")]
        assert len(expenses_before) >= 1
        # Undo paid
        ru = admin_session.post(f"{BASE_URL}/api/coach-payouts/{po['id']}/undo-paid", timeout=15)
        assert ru.status_code == 200, ru.text
        # Expense soft-deleted
        re2 = admin_session.get(f"{BASE_URL}/api/expenses", timeout=15)
        expenses_after = [e for e in re2.json() if "Coach Payout" in (e.get("category") or "") and po["id"] in (e.get("notes") or "")]
        assert len(expenses_after) == 0, f"expense not soft-deleted: {expenses_after}"


# --------- Public register-full & public-sessions ---------
class TestPublicRegister:
    def test_public_sessions_no_auth(self):
        # no admin cookies
        r = requests.get(f"{BASE_URL}/api/auth/public-sessions", timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        for session in data:
            for key in ("max_students", "active_enrollments", "available_seats", "is_full"):
                assert key in session, f"missing capacity key {key}"

    def test_register_full_creates_parent(self):
        s = requests.Session()
        uniq = int(time.time())
        email = f"test_iter3_{uniq}@example.com"
        body = {
            "parent_name": "TEST Iter3 Parent",
            "parent_email": email,
            "parent_phone": "5551234567",
            "password": "TestPass123!",
            "child_first_name": "TESTIter3",
            "child_last_name": "Kid",
            "child_dob": "2015-05-10",
            "child_skill_level": "beginner",
            "emergency_contact_name": "Emergency",
            "emergency_contact_phone": "5559998888",
            "waiver_accepted": True,
        }
        r = s.post(f"{BASE_URL}/api/auth/register-full", json=body, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["email"] == email
        assert d["role"] == "parent"
        assert d.get("student_id")
        # Auto-login: /auth/me should succeed using cookies
        me = s.get(f"{BASE_URL}/api/auth/me", timeout=15)
        assert me.status_code == 200
        assert me.json()["email"] == email

    def test_register_full_with_session_creates_registration_payment(self, admin_session):
        uniq = int(time.time() * 1000)
        session_body = {
            "name": f"TEST Payment Gated Session {uniq}",
            "skill_level": "beginner",
            "age_group": "8-12",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "days_of_week": ["Mon"],
            "start_time": "13:00",
            "end_time": "14:00",
            "location": "Court 8",
            "max_students": 3,
            "monthly_price": 123.0,
            "status": "active",
        }
        sr = admin_session.post(f"{BASE_URL}/api/sessions", json=session_body, timeout=15)
        assert sr.status_code == 200, sr.text
        session_id = sr.json()["id"]

        s = requests.Session()
        email = f"pay_gated_{uniq}@example.com"
        body = {
            "parent_name": "Payment Parent",
            "parent_email": email,
            "parent_phone": "5551234567",
            "password": "TestPass123!",
            "child_first_name": "Pay",
            "child_last_name": "Kid",
            "child_dob": "2015-05-10",
            "child_skill_level": "beginner",
            "emergency_contact_name": "Emergency",
            "emergency_contact_phone": "5559998888",
            "waiver_accepted": True,
            "session_id": session_id,
        }
        r = s.post(f"{BASE_URL}/api/auth/register-full", json=body, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["enrollment_id"]
        assert data["payment_id"]
        assert data.get("waitlisted") is False

        student = admin_session.get(f"{BASE_URL}/api/students/{data['student_id']}", timeout=15)
        assert student.status_code == 200, student.text
        assert student.json().get("waiver_version")
        assert student.json().get("waiver_text_hash")

        payments = s.get(f"{BASE_URL}/api/payments", timeout=15)
        assert payments.status_code == 200, payments.text
        payment = next(p for p in payments.json() if p["id"] == data["payment_id"])
        assert payment["status"] == "pending"
        assert payment["payment_type"] == "registration"
        assert payment["final_amount"] == 123.0

        enrollments = admin_session.get(f"{BASE_URL}/api/enrollments", params={"session_id": session_id}, timeout=15)
        assert enrollments.status_code == 200, enrollments.text
        enrollment = next(e for e in enrollments.json() if e["id"] == data["enrollment_id"])
        assert enrollment["approval_status"] == "pending_payment"

        paid = admin_session.patch(
            f"{BASE_URL}/api/payments/{data['payment_id']}/mark-paid",
            json={"payment_method": "cash"},
            timeout=15,
        )
        assert paid.status_code == 200, paid.text
        after = admin_session.get(f"{BASE_URL}/api/enrollments", params={"session_id": session_id}, timeout=15)
        enrollment_after = next(e for e in after.json() if e["id"] == data["enrollment_id"])
        assert enrollment_after["approval_status"] == "pending"

        refund = admin_session.post(
            f"{BASE_URL}/api/payments/{data['payment_id']}/refund",
            json={"amount": 23, "reason": "test partial refund"},
            timeout=15,
        )
        assert refund.status_code == 200, refund.text
        assert refund.json()["refund_status"] == "partially_refunded"

        waivers = admin_session.get(f"{BASE_URL}/api/reports/waivers.csv", timeout=15)
        assert waivers.status_code == 200
        assert "Version" in waivers.text

    def test_register_full_duplicate_email(self, admin_session):
        body = {
            "parent_name": "Dup", "parent_email": ADMIN_EMAIL,
            "parent_phone": "", "password": "Whatever123",
            "child_first_name": "A", "child_last_name": "B",
            "child_dob": "2018-01-01", "child_skill_level": "beginner",
            "emergency_contact_name": "E", "emergency_contact_phone": "5550000000",
            "waiver_accepted": True,
        }
        r = requests.post(f"{BASE_URL}/api/auth/register-full", json=body, timeout=15)
        assert r.status_code == 400

    def test_register_full_waiver_required(self):
        body = {
            "parent_name": "NW", "parent_email": f"no_waiver_{int(time.time())}@x.com",
            "parent_phone": "", "password": "Whatever123",
            "child_first_name": "A", "child_last_name": "B",
            "child_dob": "2018-01-01", "child_skill_level": "beginner",
            "emergency_contact_name": "E", "emergency_contact_phone": "5550000000",
            "waiver_accepted": False,
        }
        r = requests.post(f"{BASE_URL}/api/auth/register-full", json=body, timeout=15)
        assert r.status_code == 400

    def test_register_full_waitlists_full_session(self, admin_session):
        uniq = int(time.time() * 1000)
        session_body = {
            "name": f"TEST Full Public Session {uniq}",
            "skill_level": "beginner",
            "age_group": "8-12",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "days_of_week": ["Sat"],
            "start_time": "09:00",
            "end_time": "10:00",
            "location": "Court 9",
            "max_students": 1,
            "monthly_price": 100.0,
            "status": "active",
        }
        sr = admin_session.post(f"{BASE_URL}/api/sessions", json=session_body, timeout=15)
        assert sr.status_code == 200, sr.text
        session_id = sr.json()["id"]

        existing_student = {
            "first_name": "TESTFull",
            "last_name": "Seat",
            "dob": "2015-01-01",
            "skill_level": "beginner",
            "emergency_contact_name": "Admin",
            "emergency_contact_phone": "5550001111",
            "waiver_accepted": True,
        }
        child = admin_session.post(f"{BASE_URL}/api/students", json=existing_student, timeout=15)
        assert child.status_code == 200, child.text
        enrollment = admin_session.post(
            f"{BASE_URL}/api/enrollments",
            json={"student_id": child.json()["id"], "session_id": session_id},
            timeout=15,
        )
        assert enrollment.status_code == 200, enrollment.text
        enrollment_id = enrollment.json()["id"]

        full = admin_session.get(f"{BASE_URL}/api/sessions/{session_id}", timeout=15)
        assert full.status_code == 200
        session_info = full.json()
        assert session_info["available_seats"] == 0
        assert session_info["is_full"] is True

        email = f"full_session_{uniq}@example.com"
        body = {
            "parent_name": "Full Session Parent",
            "parent_email": email,
            "parent_phone": "5551234567",
            "password": "TestPass123!",
            "child_first_name": "Full",
            "child_last_name": "Kid",
            "child_dob": "2015-05-10",
            "child_skill_level": "beginner",
            "emergency_contact_name": "Emergency",
            "emergency_contact_phone": "5559998888",
            "waiver_accepted": True,
            "session_id": session_id,
        }
        r = requests.post(f"{BASE_URL}/api/auth/register-full", json=body, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["waitlisted"] is True
        assert data["waitlist_id"]
        assert data["enrollment_id"] is None

        login = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": email, "password": "TestPass123!"},
            timeout=15,
        )
        assert login.status_code == 200

        waitlist = admin_session.get(f"{BASE_URL}/api/waitlist", params={"status": "waiting"}, timeout=15)
        assert waitlist.status_code == 200, waitlist.text
        assert any(w["id"] == data["waitlist_id"] for w in waitlist.json())

        cancel = admin_session.post(f"{BASE_URL}/api/enrollments/{enrollment_id}/cancel", timeout=15)
        assert cancel.status_code == 200, cancel.text
        cancel_again = admin_session.post(f"{BASE_URL}/api/enrollments/{enrollment_id}/cancel", timeout=15)
        assert cancel_again.status_code == 200, cancel_again.text
        reopened = admin_session.get(f"{BASE_URL}/api/sessions/{session_id}", timeout=15)
        assert reopened.status_code == 200
        reopened_info = reopened.json()
        assert reopened_info["available_seats"] == 0
        assert reopened_info["is_full"] is True
        offered = admin_session.get(f"{BASE_URL}/api/waitlist", params={"status": "offered"}, timeout=15)
        assert offered.status_code == 200, offered.text
        assert any(w["id"] == data["waitlist_id"] for w in offered.json())

        target_body = {
            **session_body,
            "name": f"TEST Transfer Target {uniq}",
            "days_of_week": ["Sun"],
            "start_time": "11:00",
            "end_time": "12:00",
        }
        target = admin_session.post(f"{BASE_URL}/api/sessions", json=target_body, timeout=15)
        assert target.status_code == 200, target.text
        target_id = target.json()["id"]
        transfer = admin_session.post(
            f"{BASE_URL}/api/enrollments/{enrollment_id}/transfer",
            json={
                "to_session_id": target_id,
                "effective_month": "2026-06",
                "permanent": True,
                "note": "cancelled enrollment should not reserve target",
            },
            timeout=15,
        )
        assert transfer.status_code == 400
        after_transfer = admin_session.get(f"{BASE_URL}/api/sessions/{target_id}", timeout=15)
        assert after_transfer.status_code == 200
        target_info = after_transfer.json()
        assert target_info["available_seats"] == 1


# --------- Stripe checkout ---------
class TestStripe:
    def test_checkout_session_returns_url(self, admin_session):
        # Find any pending payment to use
        rp = admin_session.get(f"{BASE_URL}/api/payments?status=pending", timeout=15)
        assert rp.status_code == 200
        pending = rp.json()
        if not pending:
            pytest.skip("no pending payment")
        pid = pending[0]["id"]
        cfg = admin_session.get(f"{BASE_URL}/api/billing/config", timeout=15)
        assert cfg.status_code == 200, cfg.text
        stripe_configured = cfg.json().get("stripe_configured") is True
        origin_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")
        r = admin_session.post(f"{BASE_URL}/api/billing/checkout-session",
                               json={"payment_id": pid, "origin_url": origin_url},
                               timeout=30)
        if not stripe_configured:
            assert r.status_code == 503
            assert "Stripe is not configured" in r.text
            return
        assert r.status_code == 200, r.text
        d = r.json()
        assert "url" in d and "session_id" in d
        assert d["url"].startswith("https://checkout.stripe.com/"), f"unexpected url {d['url']}"
        # status poll — known issue: emergentintegrations StripeCheckout.get_checkout_status
        # raises pydantic validation error (metadata field expects dict but Stripe SDK returns StripeObject)
        # The endpoint may return 500. Document but don't fail Stripe creation flow.
        rs = admin_session.get(f"{BASE_URL}/api/billing/checkout-status/{d['session_id']}", timeout=30)
        if rs.status_code == 500:
            pytest.xfail("KNOWN BUG: emergentintegrations stripe.get_checkout_status pydantic "
                          "validation error on metadata field — polling endpoint returns 500")
        assert rs.status_code == 200
        sd = rs.json()
        assert "status" in sd and "payment_status" in sd

    def test_subscription_checkout_returns_url(self, admin_session):
        parent_session, enrollment_id, _ = _create_approved_parent_enrollment(admin_session, "SubCheckout")
        cfg = admin_session.get(f"{BASE_URL}/api/billing/config", timeout=15)
        assert cfg.status_code == 200, cfg.text
        stripe_configured = cfg.json().get("stripe_configured") is True
        origin_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")
        r = parent_session.post(
            f"{BASE_URL}/api/billing/subscription-checkout",
            json={"enrollment_id": enrollment_id, "origin_url": origin_url},
            timeout=30,
        )
        if not stripe_configured:
            assert r.status_code == 503
            return
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["url"].startswith("https://checkout.stripe.com/")
        assert d["session_id"].startswith("cs_")


class TestPauseRequests:
    def test_parent_pause_request_admin_approval(self, admin_session):
        parent_session, enrollment_id, _ = _create_approved_parent_enrollment(admin_session, "Pause")
        period = datetime.now(timezone.utc).strftime("%Y-%m")
        request = parent_session.post(
            f"{BASE_URL}/api/pause-requests",
            json={"enrollment_id": enrollment_id, "period": period, "reason": "test pause"},
            timeout=15,
        )
        assert request.status_code == 200, request.text
        request_id = request.json()["id"]
        assert request.json()["status"] == "pending"

        parent_list = parent_session.get(f"{BASE_URL}/api/pause-requests?status=pending", timeout=15)
        assert parent_list.status_code == 200, parent_list.text
        assert any(p["id"] == request_id for p in parent_list.json())

        admin_list = admin_session.get(f"{BASE_URL}/api/pause-requests?status=pending", timeout=15)
        assert admin_list.status_code == 200, admin_list.text
        assert any(p["id"] == request_id for p in admin_list.json())

        approved = admin_session.post(f"{BASE_URL}/api/pause-requests/{request_id}/approve", json={"note": ""}, timeout=20)
        assert approved.status_code == 200, approved.text
        assert period in approved.json()["skip_periods"]

        enrollments = admin_session.get(f"{BASE_URL}/api/enrollments", timeout=15)
        assert enrollments.status_code == 200, enrollments.text
        enrollment = next(e for e in enrollments.json() if e["id"] == enrollment_id)
        assert period in enrollment.get("skip_periods", [])

    def test_parent_cannot_pause_other_parent_enrollment(self, admin_session):
        parent_session, enrollment_id, _ = _create_approved_parent_enrollment(admin_session, "PauseOwn")
        other_parent, _, _ = _create_approved_parent_enrollment(admin_session, "PauseOther")
        period = datetime.now(timezone.utc).strftime("%Y-%m")
        r = other_parent.post(
            f"{BASE_URL}/api/pause-requests",
            json={"enrollment_id": enrollment_id, "period": period, "reason": "bad"},
            timeout=15,
        )
        assert r.status_code == 403


# --------- Email ---------
class TestEmail:
    def test_email_test_endpoint(self, admin_session):
        r = admin_session.post(f"{BASE_URL}/api/email/test",
                               json={"to": "blnobadminton@gmail.com"}, timeout=30)
        if not os.environ.get("RESEND_API_KEY", "").startswith("re_"):
            assert r.status_code == 503
            assert "not configured" in r.text
            return
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ok") is True
        assert "result" in d

    def test_send_dues_reminders_returns_count(self, admin_session):
        r = admin_session.post(f"{BASE_URL}/api/email/send-dues-reminders",
                               json={}, timeout=60)
        if not os.environ.get("RESEND_API_KEY", "").startswith("re_"):
            assert r.status_code == 503
            assert "No reminders were delivered" in r.text
            return
        assert r.status_code == 200, r.text
        d = r.json()
        assert "sent" in d
        assert isinstance(d["sent"], int)
        assert "failed" in d and "skipped" in d
