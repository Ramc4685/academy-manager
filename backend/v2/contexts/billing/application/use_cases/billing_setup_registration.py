"""Billing Setup registration read model.

Assembles, per paying parent, whether they can be charged today: no Firebase
login account yet, an account but no saved card, or a card on file
(chargeable). Cross-context signals (login-account existence, student roster)
come through Protocol ports defined here so billing does not import identity
or enrollment directly.

Autopay is per-enrollment (per child), not per-parent — see
``contexts.billing.domain.autopay_status`` and
``EnrollmentAutopayStateRepository`` in ``application/ports.py``. This module
aggregates counts across a parent's enrollments rather than treating autopay
as a single parent-level flag.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from backend.v2.contexts.billing.application.ports import (
    BillingCustomerDirectory,
    BillingSetupStudent,
    EnrollmentAutopayDirectory,
    EnrollmentAutopaySnapshot,
    LoginAccountDirectory,
    OutstandingBalanceDirectory,
    ParentStudentRoster,
)
from backend.v2.contexts.billing.domain.autopay_status import AutopayEnrollmentStatus

RegistrationState = Literal["no_account", "account_no_card", "card_on_file"]

# Enrollment autopay states from which "Enable autopay" can legally flip to
# active in ONE step (mirrors ALLOWED_AUTOPAY_ENROLLMENT_TRANSITIONS in
# autopay_status.py). "offered" is deliberately excluded: it means autopay was
# offered but the parent has not yet completed the Stripe SetupIntent consent
# flow (card/ACH disclosure versions on parent_billing_customers), so an admin
# click cannot legally skip straight to "active" — only "paused" (a parent who
# already consented before) can resume with one click.
_AUTOPAY_ENABLE_ELIGIBLE_STATES: frozenset[AutopayEnrollmentStatus] = frozenset({"paused"})


class BillingSetupRow(BaseModel):
    model_config = {"frozen": True}

    parent_id: str
    parent_name: str
    parent_email: str | None = None
    students: tuple[BillingSetupStudent, ...] = ()
    registration_state: RegistrationState
    card_label: str | None = None
    card_last4: str | None = None
    autopay_active_count: int = 0
    autopay_eligible_count: int = 0
    outstanding_balance_cents: int = 0
    charge_invoice_id: str | None = None
    charge_amount_cents: int = 0
    charge_autopay_eligible: bool = False
    last_invited_at: datetime | None = None


class BillingSetupSummary(BaseModel):
    model_config = {"frozen": True}

    families_total: int
    families_registered: int
    families_no_card: int
    outstanding_total_cents: int


class BillingSetupPage(BaseModel):
    model_config = {"frozen": True}

    rows: tuple[BillingSetupRow, ...]
    summary: BillingSetupSummary
    next_cursor: str | None = None


def _registration_state(*, has_card: bool, has_login_account: bool) -> RegistrationState:
    if has_card:
        return "card_on_file"
    if has_login_account:
        return "account_no_card"
    return "no_account"


class ListBillingSetup:
    """Assemble the Billing Setup admin page: one row per paying parent."""

    def __init__(
        self,
        *,
        roster: ParentStudentRoster,
        login_accounts: LoginAccountDirectory,
        customers: BillingCustomerDirectory,
        autopay: EnrollmentAutopayDirectory,
        balances: OutstandingBalanceDirectory,
    ) -> None:
        self._roster = roster
        self._login_accounts = login_accounts
        self._customers = customers
        self._autopay = autopay
        self._balances = balances

    async def execute(
        self,
        *,
        academy_id: str,
        status_filter: RegistrationState | Literal["all"] = "all",
        q: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
        parent_id: str | None = None,
    ) -> BillingSetupPage:
        if parent_id is not None:
            parent = await self._roster.get_parent(parent_id, academy_id=academy_id)
            parents = [parent] if parent is not None else []
            students_by_parent = {
                parent_id: await self._roster.students_for_parent(parent_id, academy_id=academy_id)
            }
            login_account_ids = (
                {parent_id}
                if await self._login_accounts.has_login_account(parent_id, academy_id=academy_id)
                else set()
            )
            customer = await self._customers.get_customer(parent_id, academy_id=academy_id)
            customers_by_parent = {parent_id: customer} if customer else {}
            balance = await self._balances.billing_setup_for_parent(
                parent_id, academy_id=academy_id
            )
            balances_by_parent = {parent_id: balance} if balance else {}
            autopay_snapshots = await self._autopay.list_parent_autopay_states(
                parent_id, academy_id=academy_id
            )
        else:
            parents = await self._roster.list_parents(academy_id=academy_id)
            parent_ids = [p.parent_id for p in parents]
            students_by_parent = await self._roster.students_for_parents(
                parent_ids, academy_id=academy_id
            )
            login_account_ids = await self._login_accounts.login_account_parent_ids(
                parent_ids, academy_id=academy_id
            )
            customers_by_parent = {
                c.parent_id: c for c in await self._customers.list_customers(academy_id=academy_id)
            }
            balances_by_parent = await self._balances.billing_setup_by_parent(academy_id=academy_id)
            autopay_snapshots = await self._autopay.list_autopay_states(academy_id=academy_id)
        parent_ids = [p.parent_id for p in parents]

        autopay_by_parent: dict[str, list[EnrollmentAutopaySnapshot]] = {}
        for snapshot in autopay_snapshots:
            autopay_by_parent.setdefault(snapshot.parent_id, []).append(snapshot)

        rows: list[BillingSetupRow] = []
        for parent in parents:
            customer = customers_by_parent.get(parent.parent_id)
            has_card = bool(customer and (customer.card_label or customer.card_last4))
            state = _registration_state(
                has_card=has_card,
                has_login_account=parent.parent_id in login_account_ids,
            )
            enrollments = autopay_by_parent.get(parent.parent_id, [])
            balance = balances_by_parent.get(parent.parent_id)
            active_count = sum(1 for e in enrollments if e.autopay_enrollment_status == "active")
            eligible_count = sum(
                1
                for e in enrollments
                if e.autopay_enrollment_status in _AUTOPAY_ENABLE_ELIGIBLE_STATES
            )
            charge_autopay_eligible = bool(
                balance
                and balance.charge_enrollment_id
                and any(
                    enrollment.enrollment_id == balance.charge_enrollment_id
                    and enrollment.autopay_enrollment_status == "active"
                    for enrollment in enrollments
                )
            )

            rows.append(
                BillingSetupRow(
                    parent_id=parent.parent_id,
                    parent_name=parent.parent_name,
                    parent_email=parent.parent_email,
                    students=tuple(students_by_parent.get(parent.parent_id, [])),
                    registration_state=state,
                    card_label=customer.card_label if customer else None,
                    card_last4=customer.card_last4 if customer else None,
                    autopay_active_count=active_count,
                    autopay_eligible_count=eligible_count,
                    outstanding_balance_cents=balance.outstanding_cents if balance else 0,
                    charge_invoice_id=balance.charge_invoice_id if balance else None,
                    charge_amount_cents=balance.charge_amount_cents if balance else 0,
                    charge_autopay_eligible=charge_autopay_eligible,
                    last_invited_at=customer.last_invited_at if customer else None,
                )
            )

        if status_filter != "all":
            rows = [r for r in rows if r.registration_state == status_filter]
        if q:
            needle = q.strip().lower()
            rows = [
                r
                for r in rows
                if needle in r.parent_name.lower() or needle in (r.parent_email or "").lower()
            ]

        rows.sort(key=lambda r: r.parent_name.lower())

        summary = BillingSetupSummary(
            families_total=len(rows),
            families_registered=sum(1 for r in rows if r.registration_state == "card_on_file"),
            families_no_card=sum(1 for r in rows if r.registration_state != "card_on_file"),
            outstanding_total_cents=sum(r.outstanding_balance_cents for r in rows),
        )

        start = 0
        if cursor:
            for index, row in enumerate(rows):
                if row.parent_id == cursor:
                    start = index + 1
                    break
        page_rows = rows[start : start + limit]
        next_cursor = page_rows[-1].parent_id if start + limit < len(rows) else None

        return BillingSetupPage(rows=tuple(page_rows), summary=summary, next_cursor=next_cursor)
