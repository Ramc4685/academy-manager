"""Contract tests for per-academy invoice numbering (Slice D).

Exercises the real Mongo-backed collaborators (MongoBillingLedgerRepository,
MongoBillingCounterRepository, MongoBillingSettingsRepository) wired into the
AddInvoiceLine use case's on-the-fly invoice creation path (Mode B), against
mongomock-motor. Covers:

- concurrent generation across many parents -> no collisions, monotonic per
  academy/month
- resets across months
- tenant isolation: two academies mint independent sequences
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from backend.v2.contexts.billing.application.use_cases.add_invoice_line import (
    AddInvoiceLine,
    AddInvoiceLineCommand,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_counter_repo import (
    MongoBillingCounterRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


async def _set_prefix(db, academy_id: str, prefix: str) -> None:
    """Seed the prefix the way the platform does (only the platform writes it)."""
    from backend.v2.shared.tenancy import tenant_scope

    with tenant_scope(academy_id):
        await MongoBillingSettingsRepository(db).set_invoice_number_prefix(prefix)


def _use_case(db) -> AddInvoiceLine:
    return AddInvoiceLine(
        ledger=MongoBillingLedgerRepository(db, clock=lambda: NOW),
        counters=MongoBillingCounterRepository(db),
        settings=MongoBillingSettingsRepository(db),
        clock=lambda: NOW,
    )


def _line_cmd(**overrides) -> dict:
    base = {
        "description": "June tuition",
        "line_type": "tuition",
        "quantity": 1,
        "unit_amount_cents": 5_000,
    }
    base.update(overrides)
    return base


async def test_concurrent_invoice_creation_across_many_parents_has_no_collisions_and_is_monotonic(
    db, acad
) -> None:
    """~250 parents concurrently trigger on-the-fly invoice creation in the same
    academy+month. Every minted invoice_number must be unique and the set of
    sequence numbers must be exactly 1..N (monotonic, no gaps, no collisions)."""
    await _set_prefix(db, acad, "BLNO")
    uc = _use_case(db)

    async def _create(i: int):
        return await uc.execute(
            AddInvoiceLineCommand(
                student_id=f"student-{i}",
                period="2026-06",
                academy_id=acad,
                parent_id=f"parent-{i}",
                **_line_cmd(),
            )
        )

    results = await asyncio.gather(*(_create(i) for i in range(250)))

    numbers = [r.invoice.invoice_number for r in results]
    assert all(n is not None for n in numbers)
    assert len(set(numbers)) == 250, "invoice numbers must not collide"

    seqs = sorted(int(n.rsplit("-", 1)[1]) for n in numbers)
    assert seqs == list(range(1, 251)), "sequence must be monotonic with no gaps or dupes"
    assert all(n.startswith("BLNO-2026-06-") for n in numbers)


async def test_invoice_numbering_resets_across_months(db, acad) -> None:
    await _set_prefix(db, acad, "BLNO")
    uc = _use_case(db)

    june = await uc.execute(
        AddInvoiceLineCommand(
            student_id="s-june",
            period="2026-06",
            academy_id=acad,
            parent_id="parent-june",
            **_line_cmd(),
        )
    )
    july = await uc.execute(
        AddInvoiceLineCommand(
            student_id="s-july",
            period="2026-07",
            academy_id=acad,
            parent_id="parent-july",
            **_line_cmd(),
        )
    )
    june_2 = await uc.execute(
        AddInvoiceLineCommand(
            student_id="s-june-2",
            period="2026-06",
            academy_id=acad,
            parent_id="parent-june-2",
            **_line_cmd(),
        )
    )

    assert june.invoice.invoice_number == "BLNO-2026-06-0001"
    assert july.invoice.invoice_number == "BLNO-2026-07-0001"
    assert june_2.invoice.invoice_number == "BLNO-2026-06-0002"


async def test_invoice_numbering_isolated_across_academies(db, acad, other_acad) -> None:
    """Two academies minting invoices in the same month get independent sequences
    and their own prefixes."""
    await _set_prefix(db, acad, "BLNO")
    await _set_prefix(db, other_acad, "OTHR")
    from backend.v2.shared.tenancy.context import _current as _tv

    token = _tv.set(acad)
    try:
        uc = _use_case(db)
        first_a = await uc.execute(
            AddInvoiceLineCommand(
                student_id="s-a1",
                period="2026-06",
                academy_id=acad,
                parent_id="parent-a1",
                **_line_cmd(),
            )
        )
        second_a = await uc.execute(
            AddInvoiceLineCommand(
                student_id="s-a2",
                period="2026-06",
                academy_id=acad,
                parent_id="parent-a2",
                **_line_cmd(),
            )
        )
    finally:
        _tv.reset(token)

    token = _tv.set(other_acad)
    try:
        uc_other = _use_case(db)
        first_b = await uc_other.execute(
            AddInvoiceLineCommand(
                student_id="s-b1",
                period="2026-06",
                academy_id=other_acad,
                parent_id="parent-b1",
                **_line_cmd(),
            )
        )
    finally:
        _tv.reset(token)

    assert first_a.invoice.invoice_number == "BLNO-2026-06-0001"
    assert second_a.invoice.invoice_number == "BLNO-2026-06-0002"
    # Other academy's sequence starts fresh at 1 under its own prefix — no
    # leakage from academy A, and never a BLNO- number.
    assert first_b.invoice.invoice_number == "OTHR-2026-06-0001"


async def test_invoice_numbering_uses_academys_configured_prefix(db, acad) -> None:
    await _set_prefix(db, acad, "ACAD")

    uc = _use_case(db)
    result = await uc.execute(
        AddInvoiceLineCommand(
            student_id="s-prefix",
            period="2026-06",
            academy_id=acad,
            parent_id="parent-prefix",
            **_line_cmd(),
        )
    )

    assert result.invoice.invoice_number == "ACAD-2026-06-0001"
