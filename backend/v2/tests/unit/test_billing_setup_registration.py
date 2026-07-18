"""Unit tests for the Billing Setup registration read model."""

from __future__ import annotations

import pytest

from backend.v2.contexts.billing.application.use_cases.billing_setup_registration import (
    BillingSetupStudent,
    EnrollmentAutopaySnapshot,
    ListBillingSetup,
    ParentBillingCustomerSnapshot,
    ParentRosterEntry,
)

ACADEMY_ID = "academy-1"


class FakeRoster:
    def __init__(self, parents: list[ParentRosterEntry], students: dict[str, list[BillingSetupStudent]]):
        self._parents = parents
        self._students = students

    async def list_parents(self, *, academy_id: str) -> list[ParentRosterEntry]:
        return self._parents

    async def students_for_parents(
        self, parent_ids: list[str], *, academy_id: str
    ) -> dict[str, list[BillingSetupStudent]]:
        return {pid: self._students.get(pid, []) for pid in parent_ids}


class FakeLoginAccounts:
    def __init__(self, parent_ids_with_accounts: set[str]):
        self._ids = parent_ids_with_accounts

    async def login_account_parent_ids(self, parent_ids: list[str], *, academy_id: str) -> set[str]:
        return {pid for pid in parent_ids if pid in self._ids}


class FakeCustomers:
    def __init__(self, customers: list[ParentBillingCustomerSnapshot]):
        self._customers = customers

    async def list_customers(self, *, academy_id: str) -> list[ParentBillingCustomerSnapshot]:
        return self._customers


class FakeAutopay:
    def __init__(self, snapshots: list[EnrollmentAutopaySnapshot]):
        self._snapshots = snapshots

    async def list_autopay_states(self, *, academy_id: str) -> list[EnrollmentAutopaySnapshot]:
        return self._snapshots


class FakeBalances:
    def __init__(self, balances: dict[str, int]):
        self._balances = balances

    async def outstanding_by_parent(self, *, academy_id: str) -> dict[str, int]:
        return self._balances


def _make_use_case(
    *,
    parents: list[ParentRosterEntry],
    students: dict[str, list[BillingSetupStudent]] | None = None,
    login_accounts: set[str] | None = None,
    customers: list[ParentBillingCustomerSnapshot] | None = None,
    autopay: list[EnrollmentAutopaySnapshot] | None = None,
    balances: dict[str, int] | None = None,
) -> ListBillingSetup:
    return ListBillingSetup(
        roster=FakeRoster(parents, students or {}),
        login_accounts=FakeLoginAccounts(login_accounts or set()),
        customers=FakeCustomers(customers or []),
        autopay=FakeAutopay(autopay or []),
        balances=FakeBalances(balances or {}),
    )


@pytest.mark.asyncio
async def test_parent_with_no_login_account_is_no_account():
    use_case = _make_use_case(
        parents=[ParentRosterEntry(parent_id="p1", parent_name="Alice Smith", parent_email="alice@example.com")],
    )
    page = await use_case.execute(academy_id=ACADEMY_ID)
    assert page.rows[0].registration_state == "no_account"


@pytest.mark.asyncio
async def test_parent_with_account_but_no_card_is_account_no_card():
    use_case = _make_use_case(
        parents=[ParentRosterEntry(parent_id="p1", parent_name="Bob Jones")],
        login_accounts={"p1"},
    )
    page = await use_case.execute(academy_id=ACADEMY_ID)
    assert page.rows[0].registration_state == "account_no_card"


@pytest.mark.asyncio
async def test_parent_with_saved_card_is_card_on_file():
    use_case = _make_use_case(
        parents=[ParentRosterEntry(parent_id="p1", parent_name="Cara Lee")],
        login_accounts={"p1"},
        customers=[
            ParentBillingCustomerSnapshot(
                parent_id="p1", stripe_customer_id="cus_1", card_label="Visa", card_last4="4242"
            )
        ],
    )
    page = await use_case.execute(academy_id=ACADEMY_ID)
    row = page.rows[0]
    assert row.registration_state == "card_on_file"
    assert row.card_label == "Visa"
    assert row.card_last4 == "4242"


@pytest.mark.asyncio
async def test_card_on_file_does_not_require_login_account_flag():
    """A saved card implies chargeable regardless of the login-account signal —
    card presence alone determines card_on_file per the "has a chargeable
    saved card" definition."""
    use_case = _make_use_case(
        parents=[ParentRosterEntry(parent_id="p1", parent_name="Dana Kim")],
        login_accounts=set(),
        customers=[
            ParentBillingCustomerSnapshot(parent_id="p1", stripe_customer_id="cus_1", card_last4="1111")
        ],
    )
    page = await use_case.execute(academy_id=ACADEMY_ID)
    assert page.rows[0].registration_state == "card_on_file"


@pytest.mark.asyncio
async def test_autopay_counts_aggregate_per_enrollment_not_per_parent():
    use_case = _make_use_case(
        parents=[ParentRosterEntry(parent_id="p1", parent_name="Eve Park")],
        autopay=[
            EnrollmentAutopaySnapshot(enrollment_id="e1", parent_id="p1", autopay_enrollment_status="active"),
            EnrollmentAutopaySnapshot(enrollment_id="e2", parent_id="p1", autopay_enrollment_status="paused"),
            EnrollmentAutopaySnapshot(enrollment_id="e3", parent_id="p1", autopay_enrollment_status="offered"),
            EnrollmentAutopaySnapshot(
                enrollment_id="e4", parent_id="p1", autopay_enrollment_status="not_offered"
            ),
        ],
    )
    page = await use_case.execute(academy_id=ACADEMY_ID)
    row = page.rows[0]
    assert row.autopay_active_count == 1
    # eligible = offered or paused (can transition straight to active); not_offered cannot yet.
    assert row.autopay_eligible_count == 2


@pytest.mark.asyncio
async def test_outstanding_balance_is_summed_per_parent():
    use_case = _make_use_case(
        parents=[ParentRosterEntry(parent_id="p1", parent_name="Fay Wu")],
        balances={"p1": 15000},
    )
    page = await use_case.execute(academy_id=ACADEMY_ID)
    assert page.rows[0].outstanding_balance_cents == 15000
    assert page.summary.outstanding_total_cents == 15000


@pytest.mark.asyncio
async def test_status_filter_narrows_to_matching_state():
    use_case = _make_use_case(
        parents=[
            ParentRosterEntry(parent_id="p1", parent_name="Ann No Account"),
            ParentRosterEntry(parent_id="p2", parent_name="Bea Card On File"),
        ],
        login_accounts=set(),
        customers=[
            ParentBillingCustomerSnapshot(parent_id="p2", stripe_customer_id="cus_2", card_last4="9999")
        ],
    )
    page = await use_case.execute(academy_id=ACADEMY_ID, status_filter="card_on_file")
    assert [r.parent_id for r in page.rows] == ["p2"]

    page_summary = await use_case.execute(academy_id=ACADEMY_ID, status_filter="no_account")
    assert [r.parent_id for r in page_summary.rows] == ["p1"]


@pytest.mark.asyncio
async def test_name_search_matches_name_or_email_case_insensitively():
    use_case = _make_use_case(
        parents=[
            ParentRosterEntry(parent_id="p1", parent_name="Grace Hopper", parent_email="grace@example.com"),
            ParentRosterEntry(parent_id="p2", parent_name="Henry Ford", parent_email="henry@example.com"),
        ],
    )
    page = await use_case.execute(academy_id=ACADEMY_ID, q="grace")
    assert [r.parent_id for r in page.rows] == ["p1"]

    page_by_email = await use_case.execute(academy_id=ACADEMY_ID, q="HENRY@EXAMPLE.COM")
    assert [r.parent_id for r in page_by_email.rows] == ["p2"]


@pytest.mark.asyncio
async def test_summary_counts_families_by_registration_state():
    use_case = _make_use_case(
        parents=[
            ParentRosterEntry(parent_id="p1", parent_name="A"),
            ParentRosterEntry(parent_id="p2", parent_name="B"),
            ParentRosterEntry(parent_id="p3", parent_name="C"),
        ],
        login_accounts={"p2"},
        customers=[
            ParentBillingCustomerSnapshot(parent_id="p3", stripe_customer_id="cus_3", card_last4="0000")
        ],
    )
    page = await use_case.execute(academy_id=ACADEMY_ID)
    assert page.summary.families_total == 3
    assert page.summary.families_registered == 1
    assert page.summary.families_no_card == 2


@pytest.mark.asyncio
async def test_pagination_cursor_returns_next_page():
    parents = [ParentRosterEntry(parent_id=f"p{i}", parent_name=f"Parent {i:02d}") for i in range(5)]
    use_case = _make_use_case(parents=parents)

    first_page = await use_case.execute(academy_id=ACADEMY_ID, limit=2)
    assert [r.parent_id for r in first_page.rows] == ["p0", "p1"]
    assert first_page.next_cursor == "p1"

    second_page = await use_case.execute(academy_id=ACADEMY_ID, limit=2, cursor=first_page.next_cursor)
    assert [r.parent_id for r in second_page.rows] == ["p2", "p3"]
