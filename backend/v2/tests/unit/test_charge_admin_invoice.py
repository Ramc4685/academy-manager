"""The audited admin-charge path (#664 follow-up)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.billing.application.charge_admin_invoice import (
    charge_invoice_as_admin,
)

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


@dataclass
class _Invoice:
    parent_id: str
    status: str = "open"
    balance_due_cents: int = 6000


class _Idem:
    """Insert-only, like MongoIdempotencyStore."""

    def __init__(self) -> None:
        self.store: dict[str, Any] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def put(self, key: str, value: dict[str, Any]) -> None:
        if key in self.store:
            raise DuplicateKeyError(key)
        self.store[key] = value


class _Customers:
    def __init__(self, has_card: bool = True) -> None:
        self.has_card = has_card

    async def has_saved_card(self, *, parent_id: str) -> bool:
        return self.has_card


class _Ledger:
    def __init__(self, invoice) -> None:
        self.invoice = invoice

    async def get_invoice(self, invoice_id: str):
        return self.invoice


class _Attempts:
    def __init__(self, attempt=None) -> None:
        self.attempt = attempt

    async def find_latest_attempt(self, *, academy_id, invoice_id, request_id):
        return self.attempt


class _Audit:
    def __init__(self) -> None:
        self.entries: list[Any] = []

    async def append(self, entry) -> None:
        if any(e.audit_id == entry.audit_id for e in self.entries):
            return
        self.entries.append(entry)


def _charger(calls: list[dict[str, Any]]):
    async def charge(invoice_id, *, source, actor_id, retry_scope):
        calls.append(
            {"invoice_id": invoice_id, "source": source, "actor_id": actor_id, "scope": retry_scope}
        )
        return {
            "invoice_id": invoice_id,
            "success": True,
            "status": "paid",
            "balance_due_cents": 0,
            "attempted_amount_cents": 6000,
            "requires_action": False,
            "decline_code": None,
        }

    return charge


async def _run(**over):
    calls: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = dict(
        idempotency=_Idem(),
        customers=_Customers(),
        ledger=_Ledger(_Invoice(parent_id="p-1")),
        attempts=_Attempts(),
        charge=_charger(calls),
        audit=_Audit(),
        academy_id="acad",
        parent_id="p-1",
        invoice_id="inv-1",
        actor_id="admin-1",
        request_id="req-1",
        reason="parent asked on the phone",
        source="admin_manual",
        audit_kind="admin-charge",
        idem_prefix="admin_charge",
        clock=lambda: NOW,
    )
    kwargs.update(over)
    payload = await charge_invoice_as_admin(**kwargs)
    return payload, kwargs, calls


@pytest.mark.asyncio
async def test_charge_is_attributed_and_audited_with_the_reason() -> None:
    payload, kw, calls = await _run()

    assert payload["success"] is True
    assert calls[0]["source"] == "admin_manual"
    assert calls[0]["actor_id"] == "admin-1"
    entry = kw["audit"].entries[0]
    assert entry.action == "admin_charge_initiated"
    assert entry.reason == "parent asked on the phone"
    assert entry.actor_id == "admin-1"
    assert entry.parent_id == "p-1"


@pytest.mark.asyncio
async def test_replay_returns_the_cached_payload_without_charging_twice() -> None:
    idem, audit = _Idem(), _Audit()
    calls: list[dict[str, Any]] = []
    shared = dict(idempotency=idem, audit=audit, charge=_charger(calls))

    await _run(**shared)
    await _run(**shared)

    assert len(calls) == 1, "a replay must not put a second charge through Stripe"
    assert len(audit.entries) == 1


@pytest.mark.asyncio
async def test_confirmed_amount_that_moved_aborts_instead_of_charging() -> None:
    calls: list[dict[str, Any]] = []
    with pytest.raises(ValueError, match="charge_target_changed"):
        await _run(expected_amount_cents=9999, charge=_charger(calls))
    assert calls == []


@pytest.mark.asyncio
async def test_no_saved_card_is_refused() -> None:
    with pytest.raises(ValueError, match="no_saved_payment_method"):
        await _run(customers=_Customers(has_card=False))


@pytest.mark.asyncio
async def test_invoice_belonging_to_another_parent_is_refused() -> None:
    with pytest.raises(ValueError, match="charge_target_changed"):
        await _run(ledger=_Ledger(_Invoice(parent_id="p-other")))


@pytest.mark.asyncio
async def test_a_charge_still_in_flight_is_not_duplicated() -> None:
    idem = _Idem()
    await idem.put(
        "admin_charge:acad:admin-1:p-1:inv-1:any:req-1",
        {"started_at": (NOW - timedelta(seconds=5)).isoformat()},
    )
    calls: list[dict[str, Any]] = []
    with pytest.raises(ValueError, match="charge_in_progress"):
        await _run(idempotency=idem, charge=_charger(calls))
    assert calls == []
