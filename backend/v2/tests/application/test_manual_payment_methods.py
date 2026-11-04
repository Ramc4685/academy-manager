"""``UpdateManualPaymentMethods``: validation, no-op, one audit entry per change."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.contexts.billing.application.use_cases.manual_payment_methods import (
    MANUAL_PAYMENT_METHODS,
    ManualPaymentMethodsValidationError,
    UpdateManualPaymentMethods,
    UpdateManualPaymentMethodsCommand,
)

ALL_SIX = ["cash", "check", "zelle", "venmo", "bank_transfer", "other"]
NOW = datetime(2026, 9, 28, 15, 0, tzinfo=UTC)


class _Store:
    def __init__(self, methods: list[str] | None = None) -> None:
        self.methods = list(methods or ALL_SIX)
        self.writes: list[tuple[str, list[str], str]] = []
        self.audit: list[Any] = []

    async def read(self, academy_id: str) -> list[str]:
        return list(self.methods)

    async def write(self, academy_id: str, methods: list[str], *, actor_id: str) -> list[str]:
        self.writes.append((academy_id, methods, actor_id))
        self.methods = list(methods)
        return list(methods)

    async def append(self, entry: Any) -> None:
        self.audit.append(entry)


class _Fn:
    def __init__(self, fn: Any) -> None:
        self.execute = fn


def _use_case(store: _Store) -> UpdateManualPaymentMethods:
    return UpdateManualPaymentMethods(
        reader=_Fn(store.read), writer=_Fn(store.write), audit=store, clock=lambda: NOW
    )


def _cmd(methods: list[str], reason: str | None = None) -> UpdateManualPaymentMethodsCommand:
    return UpdateManualPaymentMethodsCommand(
        manual_methods=methods, actor_id="u-owner", reason=reason
    )


def test_billing_set_matches_the_dialogs_list() -> None:
    assert list(MANUAL_PAYMENT_METHODS) == ALL_SIX


async def test_a_change_is_written_in_canonical_order_and_audited() -> None:
    store = _Store()
    saved = await _use_case(store).execute("acad", _cmd(["zelle", "cash", "zelle"], "no venmo"))

    assert saved == ["cash", "zelle"]
    assert store.writes == [("acad", ["cash", "zelle"], "u-owner")]
    assert len(store.audit) == 1
    entry = store.audit[0]
    assert entry.action == "payment_methods_changed"
    assert entry.academy_id == "acad"
    assert entry.actor_id == "u-owner"
    assert entry.reason == "no venmo"
    assert entry.at == NOW
    assert entry.before == {"manual_methods": ALL_SIX}
    assert entry.after == {"manual_methods": ["cash", "zelle"]}


async def test_saving_the_current_list_writes_and_audits_nothing() -> None:
    store = _Store()
    assert await _use_case(store).execute("acad", _cmd(list(reversed(ALL_SIX)))) == ALL_SIX
    assert store.writes == []
    assert store.audit == []


@pytest.mark.parametrize("bad", [[], ["cash", "wire"], ["CASH"]])
async def test_invalid_choice_is_refused_before_any_write(bad: list[str]) -> None:
    store = _Store()
    with pytest.raises(ManualPaymentMethodsValidationError) as exc:
        await _use_case(store).execute("acad", _cmd(bad))
    assert exc.value.field == "manual_methods"
    assert store.writes == []
    assert store.audit == []


async def test_an_audit_failure_does_not_hide_the_write() -> None:
    store = _Store()

    class _BrokenAudit:
        async def append(self, entry: Any) -> None:
            raise RuntimeError("audit down")

    use_case = UpdateManualPaymentMethods(
        reader=_Fn(store.read), writer=_Fn(store.write), audit=_BrokenAudit(), clock=lambda: NOW
    )
    assert await use_case.execute("acad", _cmd(["cash"])) == ["cash"]
    assert store.methods == ["cash"]
