"""``$or`` lookups must carry ``academy_id`` inside every branch (#878)."""

from __future__ import annotations

from backend.v2.composition.invoice_naming import invoice_id_or_number_filter


def test_every_branch_is_tenant_scoped_so_the_partial_indexes_apply() -> None:
    query = invoice_id_or_number_filter("acad-a", "INV-0007")

    assert query["academy_id"] == "acad-a"
    assert query["$or"] == [
        {"academy_id": "acad-a", "invoice_id": "INV-0007"},
        {"academy_id": "acad-a", "invoice_number": "INV-0007"},
    ]
