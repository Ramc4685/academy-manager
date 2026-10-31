"""Who was this payment for? — student-name resolution for the admin payments list.

Issue #618: ``list_payments_recent`` only ever enriched the invoice rows, so
every ledger-native row (admin-recorded manual payments and Stripe-checkout
balance payments) reached the UI with no ``student_name`` at all and rendered
as "Unassigned" — half the list, unreconcilable.

A ledger payment has no single deterministic student: it can settle several
invoices at once, or none at all (registration and family-level checkouts).
The 2026-09-13 decision therefore resolves per row, in order:

1. the row's own ``student_id`` (invoice rows carry one);
2. the invoice it was allocated to, via that invoice's ``student_id``;
3. the paying parent's only child, when the family has exactly one;
4. otherwise the parent's name with a ``(family payment)`` suffix — an honest
   label rather than a misleading "Unassigned".

Rows that already carry a name (the legacy ``payments`` projections resolve
theirs in ``MongoPaymentRepo._to_admin_row``) are never overwritten: a guess
must not displace a fact. Every lookup is batched with ``$in``; this runs over
a list capped at 1000 rows and must not become an N+1.
"""

from __future__ import annotations

from typing import Any

FAMILY_PAYMENT_SUFFIX = "(family payment)"


def _student_display_name(doc: dict[str, Any]) -> str:
    """Same shape as ``MongoPaymentRepo._to_admin_row``: full_name, else first+last."""
    full_name = str(doc.get("full_name") or "").strip()
    if full_name:
        return full_name
    first = str(doc.get("first_name") or "").strip()
    last = str(doc.get("last_name") or "").strip()
    return f"{first} {last}".strip()


def _parent_display_name(doc: dict[str, Any]) -> str:
    display = str(doc.get("display_name") or doc.get("name") or "").strip()
    if display:
        return display
    first = str(doc.get("first_name") or "").strip()
    last = str(doc.get("last_name") or "").strip()
    return f"{first} {last}".strip()


def _unresolved(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if not str(row.get("student_name") or "").strip()]


async def _names_by_student_id(db: Any, academy_id: str, student_ids: set[str]) -> dict[str, str]:
    if not student_ids:
        return {}
    names: dict[str, str] = {}
    async for doc in db["students"].find(
        {"academy_id": academy_id, "student_id": {"$in": sorted(student_ids)}},
        {"student_id": 1, "full_name": 1, "first_name": 1, "last_name": 1},
    ):
        student_id = str(doc.get("student_id") or "")
        name = _student_display_name(doc)
        if student_id and name:
            names[student_id] = name
    return names


async def _student_id_by_invoice(db: Any, academy_id: str, invoice_ids: set[str]) -> dict[str, str]:
    if not invoice_ids:
        return {}
    mapping: dict[str, str] = {}
    async for doc in db["invoices"].find(
        {"academy_id": academy_id, "invoice_id": {"$in": sorted(invoice_ids)}},
        {"invoice_id": 1, "student_id": 1},
    ):
        invoice_id = str(doc.get("invoice_id") or "")
        student_id = str(doc.get("student_id") or "")
        if invoice_id and student_id:
            mapping[invoice_id] = student_id
    return mapping


async def _children_by_parent(
    db: Any, academy_id: str, parent_ids: set[str]
) -> dict[str, list[str]]:
    if not parent_ids:
        return {}
    children: dict[str, list[str]] = {}
    async for doc in db["students"].find(
        {"academy_id": academy_id, "parent_id": {"$in": sorted(parent_ids)}},
        {"parent_id": 1, "full_name": 1, "first_name": 1, "last_name": 1},
    ):
        name = _student_display_name(doc)
        if name:
            children.setdefault(str(doc.get("parent_id") or ""), []).append(name)
    return children


async def _names_by_parent_id(db: Any, academy_id: str, parent_ids: set[str]) -> dict[str, str]:
    """Parents are addressable by user_id or firebase_uid, as in ``_enrich_parent_names``."""
    if not parent_ids:
        return {}
    id_list = sorted(parent_ids)
    names: dict[str, str] = {}
    async for doc in db["users"].find(
        {
            "academy_id": academy_id,
            "$or": [{"user_id": {"$in": id_list}}, {"firebase_uid": {"$in": id_list}}],
        }
    ):
        name = _parent_display_name(doc)
        if not name:
            continue
        for key in (str(doc.get("user_id") or ""), str(doc.get("firebase_uid") or "")):
            if key in parent_ids:
                names[key] = name
    return names


def _row_invoice_id(row: dict[str, Any]) -> str:
    return str(row.get("invoice_id") or row.get("invoice_number") or "")


async def resolve_student_names(
    db: Any,
    academy_id: str,
    rows: list[dict[str, Any]],
) -> None:
    """Fill ``student_name`` in place on every row that still lacks one (#618)."""
    pending = _unresolved(rows)
    if not pending:
        return

    invoice_ids = {_row_invoice_id(row) for row in pending if _row_invoice_id(row)}
    student_id_by_invoice = await _student_id_by_invoice(db, academy_id, invoice_ids)

    student_id_for_row: dict[int, str] = {}
    for row in pending:
        student_id = str(row.get("student_id") or "") or student_id_by_invoice.get(
            _row_invoice_id(row), ""
        )
        if student_id:
            student_id_for_row[id(row)] = student_id
    names = await _names_by_student_id(db, academy_id, set(student_id_for_row.values()))
    for row in pending:
        name = names.get(student_id_for_row.get(id(row), ""))
        if name:
            row["student_name"] = name

    pending = _unresolved(pending)
    if not pending:
        return

    parent_ids = {str(row.get("parent_id") or "") for row in pending}
    parent_ids.discard("")
    children_by_parent = await _children_by_parent(db, academy_id, parent_ids)
    for row in pending:
        siblings = children_by_parent.get(str(row.get("parent_id") or ""), [])
        if len(siblings) == 1:
            row["student_name"] = siblings[0]

    pending = _unresolved(pending)
    if not pending:
        return

    parent_names = await _names_by_parent_id(
        db, academy_id, {str(row.get("parent_id") or "") for row in pending} - {""}
    )
    for row in pending:
        parent_name = parent_names.get(str(row.get("parent_id") or ""))
        if parent_name:
            row["student_name"] = f"{parent_name} {FAMILY_PAYMENT_SUFFIX}"
