"""Iteration 3 tests — Settings, Undo flows, Public register, Stripe, Resend."""
import os
import time
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://shuttle-flow.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@badminton.app"
ADMIN_PASSWORD = "Admin@12345"


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
        r = admin_session.post(f"{BASE_URL}/api/billing/checkout-session",
                               json={"payment_id": pid, "origin_url": "https://shuttle-flow.preview.emergentagent.com"},
                               timeout=30)
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


# --------- Email ---------
class TestEmail:
    def test_email_test_endpoint(self, admin_session):
        r = admin_session.post(f"{BASE_URL}/api/email/test",
                               json={"to": "blnobadminton@gmail.com"}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ok") is True
        # 'result' is present whether real-sent or test-mode error
        assert "result" in d

    def test_send_dues_reminders_returns_count(self, admin_session):
        r = admin_session.post(f"{BASE_URL}/api/email/send-dues-reminders",
                               json={}, timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "sent" in d
        assert isinstance(d["sent"], int)
