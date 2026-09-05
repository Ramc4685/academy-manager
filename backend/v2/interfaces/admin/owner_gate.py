"""Owner-only policy for the admin BFF.

Two things live here so there is exactly one place to read the owner/admin
split from:

* :data:`OWNER_ONLY_ROUTE_PATHS` — every ``(METHOD, full_path)`` under
  ``/api/v2/admin`` that is guarded by :func:`require_owner` instead of
  ``require_persona("admin")``. The structural test
  ``tests/structural/test_owner_gate_policy.py`` enumerates the real router
  and asserts that this set and the dependency chain agree in both
  directions, so a route cannot drift onto the wrong side unnoticed.
* :func:`ensure_can_assign_role` — the action-level rule inside the (still
  admin-reachable) role-management routes: granting or revoking ``admin`` or
  ``owner`` needs the caller to hold ``owner``.

Decisions (spec ``2026-09-04-role-model-and-screens-design.md``): admins keep
recording manual payments and seeing balances, expenses, the payments list
and dues; refunds, credits, pricing, payouts/payroll, financial reports,
audit and the Stripe gateway are owner-only. Guards 404 on a missing role,
like every persona guard; the role-grant rule 403s because the caller is
already inside an authorized admin route and the message is the point.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from fastapi import HTTPException

if TYPE_CHECKING:
    from backend.v2.shared.auth.claims import AuthClaims

_ADMIN = "/api/v2/admin"

#: Roles only an owner may grant or revoke.
GOVERNANCE_ROLES: Final[frozenset[str]] = frozenset({"admin", "owner"})

OWNER_ONLY_ROUTE_PATHS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        # billing_routes.py — money governance
        ("PUT", f"{_ADMIN}/billing/settings/platform-fallback"),
        ("PUT", f"{_ADMIN}/billing/settings/invoice-schedule"),
        ("POST", f"{_ADMIN}/enrollments/{{enrollment_id}}/withdrawal-credit/approve"),
        ("POST", f"{_ADMIN}/payments/refund"),
        ("POST", f"{_ADMIN}/payments/{{payment_id}}/discount"),
        ("PUT", f"{_ADMIN}/enrollments/{{enrollment_id}}/tuition-discount"),
        ("DELETE", f"{_ADMIN}/enrollments/{{enrollment_id}}/tuition-discount"),
        ("POST", f"{_ADMIN}/payments/{{payment_id}}/undo-paid"),
        ("GET", f"{_ADMIN}/finance/payouts"),
        ("GET", f"{_ADMIN}/finance/revenue"),
        ("GET", f"{_ADMIN}/finance/tuition-discounts"),
        ("POST", f"{_ADMIN}/billing/invoices/{{invoice_id}}/adjustments"),
        ("POST", f"{_ADMIN}/billing/invoices/{{invoice_id}}/void"),
        ("POST", f"{_ADMIN}/billing/invoices/{{invoice_id}}/refund"),
        # billing_products_routes.py — pricing (GET stays admin)
        ("POST", f"{_ADMIN}/billing/products"),
        ("PATCH", f"{_ADMIN}/billing/products/{{product_id}}"),
        ("DELETE", f"{_ADMIN}/billing/products/{{product_id}}"),
        # payout_period_routes.py — every route
        ("POST", f"{_ADMIN}/payout-periods/generate"),
        ("GET", f"{_ADMIN}/payout-periods/{{period_id}}"),
        ("POST", f"{_ADMIN}/payout-periods/{{period_id}}/approve"),
        ("POST", f"{_ADMIN}/payout-periods/{{period_id}}/mark-paid"),
        ("POST", f"{_ADMIN}/payout-periods/{{period_id}}/recompute"),
        ("POST", f"{_ADMIN}/payout-periods/{{period_id}}/reopen"),
        ("PATCH", f"{_ADMIN}/payout-periods/{{period_id}}/lines/{{occurrence_id}}"),
        ("GET", f"{_ADMIN}/payout-periods/{{period_id}}/audit"),
        ("GET", f"{_ADMIN}/payout-periods/{{period_id}}/export"),
        ("GET", f"{_ADMIN}/payout-periods/{{period_id}}/payslip"),
        # payroll_routes.py — every route
        ("GET", f"{_ADMIN}/payroll/{{month}}"),
        ("POST", f"{_ADMIN}/payroll/{{month}}/generate"),
        ("POST", f"{_ADMIN}/payroll/{{month}}/recompute"),
        ("GET", f"{_ADMIN}/payroll/{{month}}/export"),
        # coach_pay_rate_routes.py — every route
        ("GET", f"{_ADMIN}/coaches/{{coach_id}}/pay-rates"),
        ("POST", f"{_ADMIN}/coaches/{{coach_id}}/pay-rates"),
        ("POST", f"{_ADMIN}/coaches/{{coach_id}}/pay-rates/repair"),
        # reports_routes.py — financial reports (dashboard, enrollment-funnel,
        # attendance-trends, coach-utilization stay admin)
        ("GET", f"{_ADMIN}/reports/session-economics"),
        ("GET", f"{_ADMIN}/reports/projected-income"),
        ("GET", f"{_ADMIN}/reports/kpis"),
        ("GET", f"{_ADMIN}/reports/refunds"),
        ("GET", f"{_ADMIN}/reports/revenue-by-category"),
        ("GET", f"{_ADMIN}/reports/deposit-slip"),
        ("GET", f"{_ADMIN}/reports/{{report_name}}.csv"),
        # audit_routes.py
        ("GET", f"{_ADMIN}/audit-logs"),
        # academy_routes.py — fees and the Stripe gateway (reads stay admin;
        # the Stripe callback carries no auth dependency at all)
        ("PATCH", f"{_ADMIN}/academy/fees"),
        ("POST", f"{_ADMIN}/academy/gateway/stripe/connect-link"),
        ("DELETE", f"{_ADMIN}/academy/gateway/stripe/connect"),
        # session_type_routes.py — per-enrollment price override
        ("POST", f"{_ADMIN}/billing-enrollments/{{enrollment_id}}/override"),
        # sessions_routes.py — ad-hoc enrollment fee
        ("POST", f"{_ADMIN}/enrollments/{{enrollment_id}}/fee"),
    }
)


def ensure_can_assign_role(claims: AuthClaims, role: str) -> None:
    """Refuse to grant or revoke ``admin``/``owner`` unless the caller is an owner.

    Called from every role-changing admin route (`create_user`, `add_user_role`,
    `remove_user_role`, `update_user_role`). Any other role (coach, parent) is
    ordinary operations work and stays open to admins. 403, not 404: the caller
    already passed the admin guard, so nothing is leaked and the message is
    what the UI needs to show.
    """

    if role in GOVERNANCE_ROLES and "owner" not in claims.roles:
        raise HTTPException(
            status_code=403,
            detail="Only the academy owner can grant or revoke admin and owner roles",
        )
