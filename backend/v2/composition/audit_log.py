"""Composition for the owner's Audit log page (``/admin/audit-logs``, S39).

One merged, paginated read over the four places a "who did what" row lives:
``audit_logs`` (account, roster and settings events), ``billing_audit_log``
(money movement and billing settings: late fees, manual payments, refunds),
``payout_audit_log`` (coach payslips) and ``coach_rate_audit_log`` (coach pay
rates). Every row comes back in one shape, newest first, with the actor
resolved in this academy's terms and a plain-words action label.

Lives outside ``composition/admin.py`` because that module sits at its wiring
line budget. Every query carries the request academy from
``current_academy_id()``; nothing tenant-specific is captured at boot.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.v2.contexts.identity.domain.audit_actors import audit_actor_fields
from backend.v2.contexts.identity.infrastructure.mongo_audit_actors import (
    MongoAuditActorDirectory,
)

# (collection, time field).
_SOURCES: tuple[tuple[str, str], ...] = (
    ("audit_logs", "created_at"),
    ("billing_audit_log", "at"),
    ("payout_audit_log", "at"),
    ("coach_rate_audit_log", "at"),
)

# Rows read per source per page before the actor filter. A filter that matches
# nothing in this window still returns a cursor, so "Load more" keeps going.
_SCAN = 500
MAX_LIMIT = 200

ACTION_LABELS: dict[str, str] = {
    "refund_issued": "Refund issued",
    "manual_payment_recorded": "Payment recorded by hand",
    "invoice_line_added": "Invoice line added",
    "invoice_line_removed": "Invoice line removed",
    "invoice_voided": "Invoice voided",
    "payment_voided": "Payment voided",
    "invoice_hand_billed": "Month billed by hand",
    "invoice_hand_created": "Invoice created by hand",
    "discount_set": "Discount set",
    "discount_removed": "Discount removed",
    "platform_fallback_toggled": "Platform charge fallback changed",
    "admin_charge_initiated": "Card charged by staff",
    "autopay_resumed": "Autopay turned on",
    "autopay_paused": "Autopay turned off",
    "invoice_schedule_changed": "Invoice schedule changed",
    "billing_rules_changed": "Billing rules changed (late fee, schedule, cancellation)",
    "late_fee_applied": "Late fee charged",
    "application_fee_changed": "Platform fee changed",
    "invoice_prefix_changed": "Invoice number prefix changed",
    "payment_methods_changed": "Offline payment methods changed",
    "session_fee_changed": "Class fee changed",
    "academy_timezone_changed": "Academy timezone changed",
    "class_plan_link_changed": "Class linked to a plan",
    "class_plan_links_matched": "Classes linked to matching plans",
    "plan_price_change_scheduled": "Plan price change scheduled",
    "plan_price_change_cancelled": "Plan price change cancelled",
    "plan_price_change_applied": "Plan price change applied",
    "referral_program_changed": "Referral programme changed",
    "sibling_discount_changed": "Sibling discount changed",
    "payment_return_unreconciled": "Bank returned part of a payment",
    "payroll_settings_changed": "Coach payroll settings changed",
    "enrollment_billing_changed": "Enrollment billing changed",
    "monthly_invoices_generated": "Monthly invoices generated",
    "class_created": "Class created",
    "waiver_published": "Waiver published",
}

# Payslip and coach-rate codes ("approved", "rate_created") only read right
# with their subject, so they are labelled per trail.
_TRAIL_LABELS: dict[str, dict[str, str]] = {
    "payout_audit_log": {
        "generated": "Payslip generated",
        "recomputed": "Payslip recomputed",
        "reopened": "Payslip reopened",
        "approved": "Payslip approved",
        "marked_paid": "Payslip marked paid",
        "line_overridden": "Payslip line changed",
        "line_override_cleared": "Payslip line change undone",
    },
    "coach_rate_audit_log": {
        "rate_created": "Coach pay rate set",
        "rate_superseded": "Coach pay rate replaced",
        "rate_repaired": "Coach pay rate repaired",
    },
}


def action_label(action: str, source: str = "audit_logs") -> str:
    """Plain words for an action code; unknown codes are humanised, never hidden."""
    label = _TRAIL_LABELS.get(source, {}).get(action) or ACTION_LABELS.get(action)
    if label is None:
        words = action.replace(".", " ").replace("_", " ").strip()
        label = words[:1].upper() + words[1:] if words else "Unknown"
    return label


def _actor_id(doc: dict[str, Any]) -> str | None:
    raw = doc.get("actor_id") or doc.get("user_id")
    if not raw:
        return None
    text = str(raw)
    # Unattended jobs write "system" or "system:<job>": that is the platform.
    return None if text == "system" or text.startswith("system:") else text


def _entity(source: str, doc: dict[str, Any]) -> tuple[str | None, str | None]:
    if source == "audit_logs":
        return (
            doc.get("entity_type") or doc.get("resource_type"),
            doc.get("entity_id") or doc.get("resource_id"),
        )
    if source == "billing_audit_log":
        for key, kind in (
            ("invoice_id", "invoice"),
            ("payment_id", "payment"),
            ("parent_id", "family"),
        ):
            if doc.get(key):
                return kind, str(doc[key])
        return "billing", None
    if source == "payout_audit_log":
        return "payout_period", str(doc.get("period_id") or "") or None
    return "coach", str(doc.get("coach_id") or "") or None


def _as_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.min.replace(tzinfo=UTC)


def _sort_key(row: dict[str, Any]) -> tuple[datetime, str, str]:
    return (row["created_at"], row["source"], row["audit_id"])


def encode_cursor(row: dict[str, Any]) -> str:
    return f"{row['created_at'].isoformat()}|{row['source']}|{row['audit_id']}"


def decode_cursor(cursor: str) -> tuple[datetime, str, str]:
    at, source, audit_id = cursor.split("|", 2)
    return (_as_utc(datetime.fromisoformat(at)), source, audit_id)


@dataclass(frozen=True)
class AdminAuditLog:
    list_page: Callable[..., Awaitable[dict[str, Any]]]


def compose_admin_audit_log(db: Any) -> AdminAuditLog:
    actors_dir = MongoAuditActorDirectory(db)

    async def list_page(
        *,
        actor_type: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        from backend.v2.shared.tenancy import current_academy_id

        academy_id = current_academy_id()
        limit = max(1, min(int(limit), MAX_LIMIT))
        after = decode_cursor(cursor) if cursor else None

        rows: list[dict[str, Any]] = []
        # The oldest key every source has fully read down to. Rows at or above
        # it are complete across sources; below it a truncated source may still
        # hold newer rows than the next source's.
        horizon: tuple[datetime, str, str] | None = None
        for source, time_field in _SOURCES:
            query: dict[str, Any] = {"academy_id": academy_id}
            if after is not None:
                # <= in Mongo, the exact tie-break below in Python.
                query[time_field] = {"$lte": after[0]}
            found = 0
            last: dict[str, Any] | None = None
            async for doc in db[source].find(query).sort([(time_field, -1)]).limit(_SCAN):
                found += 1
                entity_type, entity_id = _entity(source, doc)
                action = str(doc.get("action") or doc.get("event") or "unknown")
                row = {
                    "audit_id": str(doc.get("audit_id") or doc.get("_id")),
                    "source": source,
                    "actor_id": _actor_id(doc),
                    "action": action,
                    "action_label": action_label(action, source),
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "created_at": _as_utc(doc.get(time_field)),
                }
                last = row
                if after is None or _sort_key(row) < after:
                    rows.append(row)
            if found == _SCAN and last is not None:
                key = _sort_key(last)
                horizon = key if horizon is None or key > horizon else horizon

        rows.sort(key=_sort_key, reverse=True)
        if horizon is not None:
            rows = [row for row in rows if _sort_key(row) >= horizon]

        actors = await actors_dir.resolve(
            {str(row["actor_id"]) for row in rows if row["actor_id"]},
            academy_id=academy_id,
        )
        wanted = (actor_type or "").strip().lower()
        matched: list[dict[str, Any]] = []
        for row in rows:
            row.update(audit_actor_fields(row["actor_id"], actors))
            if not wanted or row["actor_type"] == wanted:
                matched.append(row)

        if len(matched) > limit:
            page = matched[:limit]
            return {"logs": page, "next_cursor": encode_cursor(page[-1])}
        if horizon is not None and rows:
            # Short page, but a source has more: carry on from the scan edge.
            return {"logs": matched, "next_cursor": encode_cursor(rows[-1])}
        return {"logs": matched, "next_cursor": None}

    return AdminAuditLog(list_page=list_page)
