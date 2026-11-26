"""Admin dashboard attention BFF tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock

from backend.v2.contexts.enrollment.application.use_cases.pause_requests import (
    PauseRequest,
)
from backend.v2.contexts.onboarding.application.use_cases.admin_waivers import (
    AdminWaiverReport,
    AdminWaiverSummary,
)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def test_admin_dashboard_attention_empty_state(admin_client):
    r = admin_client.get("/api/v2/admin/dashboard/attention")

    assert r.status_code == 200, r.text
    assert r.json() == {"items": [], "unavailable": []}


def test_admin_dashboard_attention_aggregates_real_signals(admin_client):
    admin_client.seed["pause_requests"].rows["pause-1"] = PauseRequest(
        pause_request_id="pause-1",
        enrollment_id="enroll-1",
        parent_id="parent-1",
        period="2026-05",
        resume_on=datetime(2026, 5, 15, tzinfo=UTC).date(),
        reason="travel",
        status="pending",
        created_at=_dt("2026-05-01T10:00:00"),
    )
    admin_client.seed["waivers"].report = AdminWaiverReport(
        summary=AdminWaiverSummary(
            total_students=5,
            signed_count=2,
            current_count=2,
            pending_count=2,
            outdated_count=1,
        ),
        rows=[],
    )

    r = admin_client.get("/api/v2/admin/dashboard/attention")

    assert r.status_code == 200, r.text
    body = r.json()
    assert [(item["kind"], item["href"], item["count"]) for item in body["items"]] == [
        ("pause_requests", "/admin/inbox?tab=pauses", 1),
        ("waivers", "/admin/settings?panel=family-policies", 3),
    ]


def test_admin_dashboard_attention_includes_billing_deferral_risks(admin_client):
    admin_client.seed["billing_deferrals"].warnings = [
        {
            "enrollment_id": "enroll-1",
            "student_id": "student-1",
            "student_name": "A Student",
            "reason_code": "stale_pause",
            "severity": "high",
        },
        {
            "enrollment_id": "enroll-2",
            "student_id": "student-2",
            "student_name": "B Student",
            "reason_code": "active_stripe_subscription_mismatch",
            "severity": "high",
        },
    ]

    r = admin_client.get("/api/v2/admin/dashboard/attention")

    assert r.status_code == 200, r.text
    item = r.json()["items"][0]
    assert item["kind"] == "billing_deferrals"
    assert item["href"] == "/admin/payments"
    assert item["count"] == 2
    assert item["severity"] == "high"


def test_admin_dashboard_attention_degrades_when_one_signal_fails(admin_client):
    admin_client.seed["pause_requests"].rows["pause-1"] = PauseRequest(
        pause_request_id="pause-1",
        enrollment_id="enroll-1",
        parent_id="parent-1",
        period="2026-05",
        resume_on=datetime(2026, 5, 15, tzinfo=UTC).date(),
        reason="travel",
        status="pending",
        created_at=_dt("2026-05-01T10:00:00"),
    )
    admin_client.use_cases.list_billing_deferral_warnings = AsyncMock(
        side_effect=RuntimeError("billing deferral query failed")
    )

    r = admin_client.get("/api/v2/admin/dashboard/attention")

    assert r.status_code == 200, r.text
    body = r.json()
    assert [(item["kind"], item["count"]) for item in body["items"]] == [
        ("pause_requests", 1),
    ]
    # L2 A0-5: the failed source is named, so the page can say "could not
    # check" instead of letting a missing card read as nothing waiting.
    assert body["unavailable"] == [
        {"source": "billing_deferral_warnings", "label": "paused billing"}
    ]


def _pending_pause(created_at: datetime) -> PauseRequest:
    return PauseRequest(
        pause_request_id="pause-1",
        enrollment_id="enroll-1",
        parent_id="parent-1",
        period="2026-05",
        resume_on=datetime(2026, 5, 15, tzinfo=UTC).date(),
        reason="travel",
        status="pending",
        created_at=created_at,
    )


def test_admin_dashboard_attention_escalates_stale_pause_requests(admin_client):
    """#616: requests sat PENDING for months because the card never aged."""
    admin_client.seed["pause_requests"].rows["pause-1"] = _pending_pause(
        datetime.now(UTC) - timedelta(days=10)
    )

    r = admin_client.get("/api/v2/admin/dashboard/attention")

    assert r.status_code == 200, r.text
    item = next(i for i in r.json()["items"] if i["kind"] == "pause_requests")
    assert item["severity"] == "high"
    assert "Oldest waiting 10 days" in item["detail"]


def test_admin_dashboard_attention_keeps_fresh_pause_requests_medium(admin_client):
    admin_client.seed["pause_requests"].rows["pause-1"] = _pending_pause(
        datetime.now(UTC) - timedelta(days=1)
    )

    r = admin_client.get("/api/v2/admin/dashboard/attention")

    assert r.status_code == 200, r.text
    item = next(i for i in r.json()["items"] if i["kind"] == "pause_requests")
    assert item["severity"] == "medium"
    assert "Oldest waiting" not in item["detail"]


def test_admin_dashboard_attention_wrong_persona_404(coach_on_admin_client, parent_on_admin_client):
    assert coach_on_admin_client.get("/api/v2/admin/dashboard/attention").status_code == 404
    assert parent_on_admin_client.get("/api/v2/admin/dashboard/attention").status_code == 404


def test_pending_registrations_reach_the_home_attention_lane(admin_client):
    """Issue #776: the family has usually already paid by this point."""
    admin_client.use_cases.admin_registration_review.list_pending = AsyncMock(
        return_value=[object(), object()]
    )

    r = admin_client.get("/api/v2/admin/dashboard/attention")

    assert r.status_code == 200, r.text
    item = r.json()["items"][0]
    assert item["kind"] == "pending_registrations"
    assert item["href"] == "/admin/inbox?tab=registrations"
    assert item["count"] == 2


def test_autopay_failure_and_dunning_exhaustion_reach_the_owner(admin_client):
    """Issue #774: both dunning signals only ever reached the parent before."""
    admin_client.seed["dunning_alerts"] = {
        "failed_autopay": 2,
        "dunning_exhausted": 1,
    }

    r = admin_client.get("/api/v2/admin/dashboard/attention")

    assert r.status_code == 200, r.text
    items = {item["attention_id"]: item for item in r.json()["items"]}
    assert items["autopay-failure"]["count"] == 2
    assert items["autopay-failure"]["href"] == "/admin/payments"
    assert items["dunning-exhaustion"]["count"] == 1
    assert items["dunning-exhaustion"]["severity"] == "high"


def test_no_dunning_alerts_means_no_autopay_cards(admin_client):
    r = admin_client.get("/api/v2/admin/dashboard/attention")

    assert r.status_code == 200, r.text
    ids = {item["attention_id"] for item in r.json()["items"]}
    assert "autopay-failure" not in ids
    assert "dunning-exhaustion" not in ids
    assert "autopay-stuck" not in ids


def test_autopay_stuck_on_our_side_reaches_the_owner(admin_client):
    """L1 A7-1: a ladder parked before any decline spends no attempt, so the
    #774 counts never showed it."""
    admin_client.seed["dunning_alerts"] = {"autopay_stuck": 3}

    r = admin_client.get("/api/v2/admin/dashboard/attention")

    assert r.status_code == 200, r.text
    items = {item["attention_id"]: item for item in r.json()["items"]}
    assert items["autopay-stuck"]["count"] == 3
    assert "not the card" in items["autopay-stuck"]["detail"]
    assert "operator" not in items["autopay-stuck"]["detail"]


def test_autopay_waiting_on_stripe_setup_says_finish_setup(admin_client):
    """L1 should-fix 8: an unfinished Stripe account is the academy's to fix."""
    admin_client.seed["dunning_alerts"] = {"autopay_needs_stripe_setup": 2}

    r = admin_client.get("/api/v2/admin/dashboard/attention")

    assert r.status_code == 200, r.text
    item = {i["attention_id"]: i for i in r.json()["items"]}["autopay-stuck"]
    assert item["count"] == 2
    assert "finish Stripe setup" in item["detail"]
    assert "our side" not in item["detail"]
    assert item["href"] == "/admin/billing-health"


def test_autopay_stuck_on_our_side_does_not_point_at_billing_health(admin_client):
    """Fix round 2: Billing health lists only Stripe setup, so a fault on our
    side must not send the owner there."""
    admin_client.seed["dunning_alerts"] = {"autopay_stuck": 1}

    r = admin_client.get("/api/v2/admin/dashboard/attention")

    item = {i["attention_id"]: i for i in r.json()["items"]}["autopay-stuck"]
    assert "Billing health" not in item["detail"]
    assert "tries again" in item["detail"]
    assert item["href"] == "/admin/payments"


def test_bank_returns_needing_a_manual_look_reach_the_owner(admin_client):
    """Fix round 2: partial or unreversible returns show in admin."""
    admin_client.seed["dunning_alerts"] = {"bank_returns_to_review": 2}

    r = admin_client.get("/api/v2/admin/dashboard/attention")

    assert r.status_code == 200, r.text
    item = {i["attention_id"]: i for i in r.json()["items"]}["bank-return-review"]
    assert item["count"] == 2
    assert item["kind"] == "bank_return_review"
    assert "manual look" in item["detail"]


def _overdue_reader(invoices: list[dict]):
    """The real cross-period reader over an in-memory Mongo (L2 B2)."""
    import asyncio

    from mongomock_motor import AsyncMongoMockClient

    from backend.v2.composition.overdue_families import OverdueFamiliesReader

    db = AsyncMongoMockClient()["dash"]
    if invoices:
        asyncio.run(db["invoices"].insert_many(invoices))

    async def chicago(_academy_id: str) -> str:
        return "America/Chicago"

    reader = OverdueFamiliesReader(
        db, academy_timezone=chicago, clock=lambda: datetime(2026, 12, 6, 3, 0, tzinfo=UTC)
    )

    class _TenantScoped:
        # The bare test app has no auth middleware to set the tenant.
        async def counts(self):
            from backend.v2.shared.tenancy import tenant_scope

            with tenant_scope("test-academy"):
                return await reader.counts()

    return _TenantScoped()


def _owing(invoice_id: str, parent: str, due: date, status: str = "open") -> dict:
    return {
        "academy_id": "test-academy",
        "invoice_id": invoice_id,
        "parent_id": parent,
        "status": status,
        "due_date": datetime(due.year, due.month, due.day, tzinfo=UTC),
        "balance_due_cents": 5000,
    }


class _BrokenOverdue:
    async def counts(self):
        raise RuntimeError("invoices down")


def test_overdue_card_counts_families_past_due_in_any_month(admin_client):
    """L2 A0-0 + B2: last month's unpaid invoice counts even when this month's
    is not yet due; drafts and not-yet-due invoices never count."""
    admin_client.app.state.admin_overdue_families = _overdue_reader(
        [
            _owing("nov", "fam-1", date(2026, 11, 5)),
            _owing("dec", "fam-1", date(2026, 12, 10)),
            _owing("oct", "fam-2", date(2026, 10, 5)),
            _owing("draft", "fam-3", date(2026, 11, 5), status="draft"),
            _owing("today", "fam-4", date(2026, 12, 5)),
        ]
    )

    r = admin_client.get("/api/v2/admin/dashboard/attention")

    assert r.status_code == 200, r.text
    item = next(i for i in r.json()["items"] if i["kind"] == "overdue_dues")
    assert item["count"] == 2
    assert item["href"] == "/admin/payments#bucket-past_due"


def test_no_past_due_families_means_no_overdue_card(admin_client):
    admin_client.app.state.admin_overdue_families = _overdue_reader([])

    r = admin_client.get("/api/v2/admin/dashboard/attention")

    assert all(i["kind"] != "overdue_dues" for i in r.json()["items"])


def test_unreadable_invoices_flag_overdue_as_unavailable(admin_client):
    admin_client.app.state.admin_overdue_families = _BrokenOverdue()

    r = admin_client.get("/api/v2/admin/dashboard/attention")

    assert r.status_code == 200, r.text
    assert {"source": "overdue_dues", "label": "overdue payments"} in r.json()["unavailable"]


def test_overdue_families_route_returns_both_counts(admin_client):
    admin_client.app.state.admin_overdue_families = _overdue_reader(
        [_owing("nov", "fam-1", date(2026, 11, 5))]
    )

    r = admin_client.get("/api/v2/admin/payments/overdue-families")

    assert r.status_code == 200, r.text
    assert r.json() == {"past_due_count": 1, "needs_action_count": 1}


def test_session_pressure_reads_the_academy_local_today(admin_client, monkeypatch):
    """L2 A0-3: 11:30 PM in Chicago is already tomorrow in UTC."""
    from backend.v2.interfaces.admin import academy_clock

    monkeypatch.setattr(academy_clock, "_now", lambda: datetime(2026, 1, 3, 5, 30, tzinfo=UTC))

    async def chicago(_academy_id: str) -> str:
        return "America/Chicago"

    admin_client.use_cases.get_academy_timezone = chicago
    seen: list[date] = []

    async def list_admin_sessions(on_date, *, window=None, coach_id=None):
        seen.append(on_date)
        return []

    admin_client.use_cases.list_admin_sessions = list_admin_sessions

    r = admin_client.get("/api/v2/admin/dashboard/attention")

    assert r.status_code == 200, r.text
    # Today's classes on the academy's date; the second read is the S10
    # unpriced-class scan, which takes no date.
    assert seen == [date(2026, 1, 2), None]


def test_unpriced_classes_with_students_are_listed_and_free_ones_are_not(admin_client):
    """S10: a fee of None with children enrolled is loud; a free class (0) is not."""
    rows = [
        {
            "session_id": "s-unpriced",
            "title": "Tuesday Intermediate",
            "amount_cents": None,
            "enrolled_count": 2,
            "status": "scheduled",
        },
        {
            "session_id": "s-free",
            "title": "Free clinic",
            "amount_cents": 0,
            "enrolled_count": 4,
            "status": "scheduled",
        },
        {
            "session_id": "s-empty",
            "title": "Empty new class",
            "amount_cents": None,
            "enrolled_count": 0,
            "status": "scheduled",
        },
    ]

    async def list_admin_sessions(on_date, *, window=None, coach_id=None):
        return rows if window == "open" else []

    admin_client.use_cases.list_admin_sessions = list_admin_sessions

    r = admin_client.get("/api/v2/admin/dashboard/attention")

    assert r.status_code == 200, r.text
    items = [i for i in r.json()["items"] if i["kind"] == "unpriced_classes"]
    assert len(items) == 1
    assert items[0]["count"] == 1
    assert items[0]["href"] == "/admin/sessions/s-unpriced"
    assert "Tuesday Intermediate (2 students)" in items[0]["detail"]
    assert "Free clinic" not in items[0]["detail"]

    rows[0]["amount_cents"] = 9000  # the owner prices it: the item clears
    r = admin_client.get("/api/v2/admin/dashboard/attention")
    assert not [i for i in r.json()["items"] if i["kind"] == "unpriced_classes"]


def test_unpriced_classes_sharing_a_title_say_which_is_which(admin_client):
    """S10 persona follow-up: two unpriced 'Tuesday Intermediate' rows read as
    one; each gets its day and start time."""
    rows = [
        {
            "session_id": f"s-{start}",
            "title": "Tuesday Intermediate",
            "amount_cents": None,
            "enrolled_count": 2,
            "status": "scheduled",
            "days_of_week": ["Tue"],
            "start_time": start,
        }
        for start in ("09:00", "17:30")
    ]

    async def list_admin_sessions(on_date, *, window=None, coach_id=None):
        return rows if window == "open" else []

    admin_client.use_cases.list_admin_sessions = list_admin_sessions

    r = admin_client.get("/api/v2/admin/dashboard/attention")

    detail = next(i for i in r.json()["items"] if i["kind"] == "unpriced_classes")["detail"]
    assert "Tuesday Intermediate, Tue 09:00 (2 students)" in detail
    assert "Tuesday Intermediate, Tue 17:30 (2 students)" in detail


class _Unbilled:
    def __init__(self, count: int) -> None:
        self._count = count
        self.periods: list[str] = []

    async def count(self, period: str) -> int:
        self.periods.append(period)
        return self._count


def test_unbilled_students_item_links_to_generate_monthly(admin_client):
    reader = _Unbilled(3)
    admin_client.app.state.admin_unbilled_students = reader

    r = admin_client.get("/api/v2/admin/dashboard/attention")

    assert r.status_code == 200, r.text
    item = next(i for i in r.json()["items"] if i["kind"] == "unbilled_students")
    assert item["count"] == 3
    assert item["href"] == "/admin/payments?tab=invoices"
    assert "3 students have no invoice for" in item["detail"]
    # The academy's current month, as YYYY-MM.
    assert len(reader.periods) == 1 and len(reader.periods[0]) == 7


def test_everyone_invoiced_means_no_unbilled_item(admin_client):
    admin_client.app.state.admin_unbilled_students = _Unbilled(0)

    r = admin_client.get("/api/v2/admin/dashboard/attention")

    assert all(i["kind"] != "unbilled_students" for i in r.json()["items"])


def test_unreadable_unbilled_count_is_unavailable_not_zero(admin_client):
    admin_client.app.state.admin_unbilled_students = _BrokenOverdue()

    r = admin_client.get("/api/v2/admin/dashboard/attention")

    assert {"source": "unbilled_students", "label": "students with no invoice"} in r.json()[
        "unavailable"
    ]
