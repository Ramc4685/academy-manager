#!/usr/bin/env python3
"""Validate the BLNO synthetic scale plan without touching Mongo.

The scale generator is intentionally deterministic. This companion check builds
the plan in memory and fails fast if it contains values that look live,
tenant-mismatched, or non-synthetic.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from collections.abc import Iterable, Mapping
from typing import Any

import scale_blno_staging

ACADEMY_ID = scale_blno_staging.ACADEMY_ID
LOCAL_EMAIL_SUFFIX = "@local.academy.test"
SYNTHETIC_SOURCE = "synthetic-local-scale-seed"
ALLOWED_IPS = {"127.0.0.1", "::1"}
LIVE_MARKERS = (
    "sk_live",
    "pk_live",
    "rk_live",
    "whsec_",
    "mongodb+srv://",
    "service_account",
    "serviceAccount",
    "private_key",
    "firebase-adminsdk",
    ".apps.googleusercontent.com",
)
DISALLOWED_EMAIL_SUFFIXES = (
    "@gmail.com",
    "@yahoo.com",
    "@outlook.com",
    "@hotmail.com",
    "@icloud.com",
)
STRIPE_LIKE_PREFIXES = ("cus_", "sub_", "pi_", "cs_")
ALLOWED_STRIPE_PREFIXES = (
    "cus_blno_scale_",
    "sub_blno_scale_",
    "pi_blno_scale_",
    "cs_blno_scale_",
)
MONTH_RE = re.compile(r"^2026-(0[1-9]|1[0-2])$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")

COLLECTION_ATTRS: tuple[tuple[str, str], ...] = (
    ("users", "users"),
    ("academy_memberships", "memberships"),
    ("parent_billing_customers", "parent_billing_customers"),
    ("subscriptions", "subscriptions"),
    ("students", "students"),
    ("enrollments", "enrollments"),
    ("invoices", "invoices"),
    ("invoice_lines", "invoice_lines"),
    ("ledger_payments", "ledger_payments"),
    ("payment_allocations", "payment_allocations"),
    ("payout_periods", "payout_periods"),
    ("payout_period_lines", "payout_period_lines"),
    ("onboarding_applications", "onboarding_applications"),
    ("waiver_templates", "waiver_templates"),
    ("waiver_signatures", "waiver_signatures"),
)

ID_PREFIXES_BY_FIELD: dict[str, tuple[str, ...]] = {
    "user_id": ("user_scale_parent_",),
    "firebase_uid": ("user_scale_parent_",),
    "auth_uid": ("user_scale_parent_",),
    "membership_id": ("mem_scale_parent_",),
    "parent_id": ("user_scale_parent_",),
    "parent_user_id": ("user_scale_parent_",),
    "student_id": ("std_scale_",),
    "enrollment_id": ("enr_scale_",),
    "invoice_id": ("inv_scale_",),
    "line_id": ("line_scale_",),
    "payment_id": ("lp_scale_", "pay_blno_scale_"),
    "allocation_id": ("alloc_scale_",),
    "period_id": ("pp_blno_scale_",),
    "waiver_template_id": ("wt_blno_scale_",),
    "waiver_signature_id": ("ws_blno_scale_",),
    "application_id": ("app_blno_scale_",),
}


@dataclasses.dataclass(frozen=True)
class SafetyIssue:
    collection: str
    index: int
    field: str
    message: str
    value: str


def _plan_rows(
    plan: scale_blno_staging.ScalePlan,
) -> Iterable[tuple[str, list[dict[str, Any]]]]:
    for collection, attr in COLLECTION_ATTRS:
        yield collection, getattr(plan, attr)


def _walk_strings(value: Any, path: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            next_path = f"{path}.{key}" if path else str(key)
            yield from _walk_strings(item, next_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_strings(item, f"{path}[{index}]")
    elif isinstance(value, str):
        yield path, value


def _add_issue(
    issues: list[SafetyIssue],
    *,
    collection: str,
    index: int,
    field: str,
    message: str,
    value: Any,
) -> None:
    text = str(value)
    if len(text) > 120:
        text = f"{text[:117]}..."
    issues.append(
        SafetyIssue(
            collection=collection,
            index=index,
            field=field,
            message=message,
            value=text,
        )
    )


def expected_counts(
    *,
    parent_count: int,
    students_per_parent: int,
    months: list[str],
) -> dict[str, int]:
    students = parent_count * students_per_parent
    invoices = students * len(months)
    paid_invoices = sum(
        1
        for parent_num in range(1, parent_count + 1)
        for student_num in range(1, students_per_parent + 1)
        for month_index, _month in enumerate(months)
        if scale_blno_staging._invoice_status(parent_num, student_num, month_index)
        == "paid"
    )
    return {
        "users": parent_count,
        "academy_memberships": parent_count,
        "parent_billing_customers": parent_count,
        "subscriptions": parent_count,
        "students": students,
        "enrollments": students,
        "invoices": invoices,
        "invoice_lines": invoices,
        "ledger_payments": paid_invoices,
        "payment_allocations": paid_invoices,
        "payout_periods": 1,
        "payout_period_lines": 1,
        "onboarding_applications": 1,
        "waiver_templates": 1,
        "waiver_signatures": 1,
    }


def _validate_counts(
    plan: scale_blno_staging.ScalePlan,
    *,
    parent_count: int,
    students_per_parent: int,
    months: list[str],
    issues: list[SafetyIssue],
) -> None:
    expected = expected_counts(
        parent_count=parent_count,
        students_per_parent=students_per_parent,
        months=months,
    )
    for collection, expected_count in expected.items():
        actual_count = plan.counts.get(collection)
        if actual_count != expected_count:
            _add_issue(
                issues,
                collection=collection,
                index=-1,
                field="count",
                message="Generated count does not match the requested scale.",
                value=f"expected={expected_count} actual={actual_count}",
            )


def _validate_row(
    *,
    collection: str,
    index: int,
    row: dict[str, Any],
    issues: list[SafetyIssue],
) -> None:
    academy_id = row.get("academy_id")
    if academy_id is not None and academy_id != ACADEMY_ID:
        _add_issue(
            issues,
            collection=collection,
            index=index,
            field="academy_id",
            message="Tenant-owned row is not scoped to BLNO.",
            value=academy_id,
        )

    source = row.get("source")
    if source is not None and source != SYNTHETIC_SOURCE:
        _add_issue(
            issues,
            collection=collection,
            index=index,
            field="source",
            message="Generated source marker is not synthetic-local.",
            value=source,
        )

    for field, prefixes in ID_PREFIXES_BY_FIELD.items():
        value = row.get(field)
        if value is not None and not str(value).startswith(prefixes):
            _add_issue(
                issues,
                collection=collection,
                index=index,
                field=field,
                message="Generated identifier does not use an approved synthetic prefix.",
                value=value,
            )
        if value is not None and not SAFE_ID_RE.fullmatch(str(value)):
            _add_issue(
                issues,
                collection=collection,
                index=index,
                field=field,
                message="Generated identifier contains unsafe characters.",
                value=value,
            )

    for field_path, value in _walk_strings(row):
        lower_value = value.lower()
        if any(marker.lower() in lower_value for marker in LIVE_MARKERS):
            _add_issue(
                issues,
                collection=collection,
                index=index,
                field=field_path,
                message="Value contains a live-secret or production-service marker.",
                value=value,
            )

        if "email" in field_path.lower():
            if not lower_value.endswith(LOCAL_EMAIL_SUFFIX):
                _add_issue(
                    issues,
                    collection=collection,
                    index=index,
                    field=field_path,
                    message="Email is not in the reserved local synthetic domain.",
                    value=value,
                )
            if lower_value.endswith(DISALLOWED_EMAIL_SUFFIXES):
                _add_issue(
                    issues,
                    collection=collection,
                    index=index,
                    field=field_path,
                    message="Email uses a consumer/live domain.",
                    value=value,
                )

        if field_path.endswith("phone") and not value.startswith("555"):
            _add_issue(
                issues,
                collection=collection,
                index=index,
                field=field_path,
                message="Phone number does not use the synthetic 555 pattern.",
                value=value,
            )

        if field_path.endswith("ip_address") and value not in ALLOWED_IPS:
            _add_issue(
                issues,
                collection=collection,
                index=index,
                field=field_path,
                message="IP address is not a local loopback address.",
                value=value,
            )

        if value.startswith(STRIPE_LIKE_PREFIXES) and not value.startswith(
            ALLOWED_STRIPE_PREFIXES
        ):
            _add_issue(
                issues,
                collection=collection,
                index=index,
                field=field_path,
                message="Stripe-like reference is not clearly synthetic BLNO scale data.",
                value=value,
            )


def _validate_months(months: list[str], issues: list[SafetyIssue]) -> None:
    if not months:
        _add_issue(
            issues,
            collection="plan",
            index=-1,
            field="months",
            message="Month list must not be empty.",
            value=months,
        )
        return
    for month in months:
        if not MONTH_RE.fullmatch(month):
            _add_issue(
                issues,
                collection="plan",
                index=-1,
                field="months",
                message="Month must use the approved local audit YYYY-MM format.",
                value=month,
            )


def _by(rows: list[dict[str, Any]], key: str) -> dict[Any, dict[str, Any]]:
    return {row[key]: row for row in rows}


def _validate_relationships(
    plan: scale_blno_staging.ScalePlan,
    issues: list[SafetyIssue],
) -> None:
    users = _by(plan.users, "user_id")
    students = _by(plan.students, "student_id")
    enrollments = _by(plan.enrollments, "enrollment_id")
    invoices = _by(plan.invoices, "invoice_id")
    payments = _by(plan.ledger_payments, "payment_id")
    paid_invoice_ids = {
        invoice["invoice_id"]
        for invoice in plan.invoices
        if invoice["status"] == "paid"
    }
    open_invoice_ids = {
        invoice["invoice_id"]
        for invoice in plan.invoices
        if invoice["status"] == "open"
    }
    payment_invoice_ids = {payment["invoice_id"] for payment in plan.ledger_payments}

    for index, student in enumerate(plan.students):
        if student["parent_id"] not in users:
            _add_issue(
                issues,
                collection="students",
                index=index,
                field="parent_id",
                message="Student parent does not exist in generated users.",
                value=student["parent_id"],
            )

    for index, enrollment in enumerate(plan.enrollments):
        if enrollment["student_id"] not in students:
            _add_issue(
                issues,
                collection="enrollments",
                index=index,
                field="student_id",
                message="Enrollment student does not exist in generated students.",
                value=enrollment["student_id"],
            )

    for index, invoice in enumerate(plan.invoices):
        if invoice["parent_id"] not in users:
            _add_issue(
                issues,
                collection="invoices",
                index=index,
                field="parent_id",
                message="Invoice parent does not exist in generated users.",
                value=invoice["parent_id"],
            )
        if invoice["student_id"] not in students:
            _add_issue(
                issues,
                collection="invoices",
                index=index,
                field="student_id",
                message="Invoice student does not exist in generated students.",
                value=invoice["student_id"],
            )
        if invoice["enrollment_id"] not in enrollments:
            _add_issue(
                issues,
                collection="invoices",
                index=index,
                field="enrollment_id",
                message="Invoice enrollment does not exist in generated enrollments.",
                value=invoice["enrollment_id"],
            )
        expected_balance = 0 if invoice["status"] == "paid" else invoice["total_cents"]
        if invoice["balance_due_cents"] != expected_balance:
            _add_issue(
                issues,
                collection="invoices",
                index=index,
                field="balance_due_cents",
                message="Invoice balance does not match generated status.",
                value=invoice["balance_due_cents"],
            )

    for index, line in enumerate(plan.invoice_lines):
        invoice = invoices.get(line["invoice_id"])
        if invoice is None:
            _add_issue(
                issues,
                collection="invoice_lines",
                index=index,
                field="invoice_id",
                message="Invoice line points to a missing invoice.",
                value=line["invoice_id"],
            )
        elif line["amount_cents"] != invoice["total_cents"]:
            _add_issue(
                issues,
                collection="invoice_lines",
                index=index,
                field="amount_cents",
                message="Invoice line amount does not match invoice total.",
                value=line["amount_cents"],
            )

    if payment_invoice_ids != paid_invoice_ids:
        extra_payments = sorted(payment_invoice_ids - paid_invoice_ids)
        missing_payments = sorted(paid_invoice_ids - payment_invoice_ids)
        _add_issue(
            issues,
            collection="ledger_payments",
            index=-1,
            field="invoice_id",
            message="Payments must exist exactly for paid invoices.",
            value={
                "extra": extra_payments[:5],
                "missing": missing_payments[:5],
                "open_with_payment": sorted(open_invoice_ids & payment_invoice_ids)[:5],
            },
        )

    for index, payment in enumerate(plan.ledger_payments):
        invoice = invoices.get(payment["invoice_id"])
        if invoice is not None and payment["amount_cents"] != invoice["total_cents"]:
            _add_issue(
                issues,
                collection="ledger_payments",
                index=index,
                field="amount_cents",
                message="Payment amount does not match invoice total.",
                value=payment["amount_cents"],
            )

    for index, allocation in enumerate(plan.payment_allocations):
        payment = payments.get(allocation["payment_id"])
        invoice = invoices.get(allocation["invoice_id"])
        if payment is None:
            _add_issue(
                issues,
                collection="payment_allocations",
                index=index,
                field="payment_id",
                message="Allocation points to a missing payment.",
                value=allocation["payment_id"],
            )
            continue
        if invoice is None:
            _add_issue(
                issues,
                collection="payment_allocations",
                index=index,
                field="invoice_id",
                message="Allocation points to a missing invoice.",
                value=allocation["invoice_id"],
            )
            continue
        if allocation["amount_cents"] != payment["amount_cents"]:
            _add_issue(
                issues,
                collection="payment_allocations",
                index=index,
                field="amount_cents",
                message="Allocation amount does not match payment amount.",
                value=allocation["amount_cents"],
            )


def _query_has_synthetic_marker(query: Mapping[str, Any]) -> bool:
    synthetic_markers = (
        "scale_",
        "_scale_",
        "blno_scale",
        "^user_scale_parent_",
        "^mem_scale_parent_",
        "^std_scale_",
        "^enr_scale_",
        "^inv_scale_",
        "^line_scale_",
        "^lp_scale_",
        "^alloc_scale_",
    )
    return any(
        marker in value
        for _path, value in _walk_strings(query)
        for marker in synthetic_markers
    )


def _validate_cleanup_filters(issues: list[SafetyIssue]) -> None:
    for index, (collection, query) in enumerate(
        scale_blno_staging.synthetic_scale_cleanup_filters()
    ):
        if not query:
            _add_issue(
                issues,
                collection=collection,
                index=index,
                field="cleanup_filter",
                message="Cleanup filter must never be empty.",
                value=query,
            )
            continue

        if collection == "users":
            user_filter = query.get("user_id")
            if not (
                isinstance(user_filter, Mapping)
                and user_filter.get("$regex") == "^user_scale_parent_"
            ):
                _add_issue(
                    issues,
                    collection=collection,
                    index=index,
                    field="cleanup_filter.user_id",
                    message="Global user cleanup must be scoped by synthetic user prefix.",
                    value=query,
                )
            continue

        if query.get("academy_id") != ACADEMY_ID:
            _add_issue(
                issues,
                collection=collection,
                index=index,
                field="cleanup_filter.academy_id",
                message="Tenant-owned cleanup filter must be scoped to BLNO.",
                value=query,
            )
        if not _query_has_synthetic_marker(query):
            _add_issue(
                issues,
                collection=collection,
                index=index,
                field="cleanup_filter",
                message="Cleanup filter must include a synthetic exact or prefix selector.",
                value=query,
            )


def validate_plan(
    plan: scale_blno_staging.ScalePlan,
    *,
    parent_count: int,
    students_per_parent: int,
    months: list[str],
) -> list[SafetyIssue]:
    issues: list[SafetyIssue] = []
    _validate_months(months, issues)
    _validate_counts(
        plan,
        parent_count=parent_count,
        students_per_parent=students_per_parent,
        months=months,
        issues=issues,
    )
    for collection, rows in _plan_rows(plan):
        for index, row in enumerate(rows):
            _validate_row(collection=collection, index=index, row=row, issues=issues)
    _validate_relationships(plan, issues)
    _validate_cleanup_filters(issues)
    return issues


def build_report(
    *,
    plan: scale_blno_staging.ScalePlan,
    issues: list[SafetyIssue],
    parent_count: int,
    students_per_parent: int,
    months: list[str],
) -> dict[str, Any]:
    return {
        "result": "fail" if issues else "pass",
        "academy_id": ACADEMY_ID,
        "requested": {
            "parents": parent_count,
            "students_per_parent": students_per_parent,
            "months": months,
        },
        "counts": plan.counts,
        "expected_counts": expected_counts(
            parent_count=parent_count,
            students_per_parent=students_per_parent,
            months=months,
        ),
        "checks": {
            "mongo_touched": False,
            "local_email_suffix": LOCAL_EMAIL_SUFFIX,
            "synthetic_source": SYNTHETIC_SOURCE,
            "live_markers": list(LIVE_MARKERS),
        },
        "issues": [dataclasses.asdict(issue) for issue in issues],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# BLNO Scale Seed Safety Validation",
        "",
        f"- Result: `{report['result']}`",
        f"- Academy: `{report['academy_id']}`",
        f"- Mongo touched: `{str(report['checks']['mongo_touched']).lower()}`",
        "",
        "## Counts",
        "",
        "| Collection | Expected | Actual |",
        "| --- | ---: | ---: |",
    ]
    counts = report["counts"]
    for collection, expected in report["expected_counts"].items():
        lines.append(f"| `{collection}` | {expected} | {counts.get(collection, 0)} |")
    lines.extend(["", "## Issues", ""])
    if not report["issues"]:
        lines.append("No safety issues found.")
    else:
        for issue in report["issues"]:
            lines.append(
                "- "
                f"`{issue['collection']}[{issue['index']}].{issue['field']}`: "
                f"{issue['message']} (`{issue['value']}`)"
            )
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parents", type=int, default=250)
    parser.add_argument("--students-per-parent", type=int, default=2)
    parser.add_argument("--months", default=",".join(scale_blno_staging.DEFAULT_MONTHS))
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    months = [month.strip() for month in args.months.split(",") if month.strip()]
    plan = scale_blno_staging.build_scale_plan(
        parent_count=args.parents,
        students_per_parent=args.students_per_parent,
        months=months,
    )
    issues = validate_plan(
        plan,
        parent_count=args.parents,
        students_per_parent=args.students_per_parent,
        months=months,
    )
    report = build_report(
        plan=plan,
        issues=issues,
        parent_count=args.parents,
        students_per_parent=args.students_per_parent,
        months=months,
    )
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_markdown(report))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
