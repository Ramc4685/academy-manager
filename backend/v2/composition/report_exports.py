"""Composition for the S41 invoices and aging CSV exports.

Lives outside ``composition/admin.py`` because that module sits at its wiring
line budget. The renderer resolves the tenant from ``current_academy_id()`` at
request time; nothing tenant-specific is captured here.
"""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.billing.infrastructure.admin_reports_read_model import (
    make_billing_exports_csv,
)


def compose_report_exports(db: Any) -> Any:
    return make_billing_exports_csv(db)
