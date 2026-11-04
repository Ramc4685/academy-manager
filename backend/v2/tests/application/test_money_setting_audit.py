"""RecordMoneySettingChange: one billing audit entry per real owner change."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.contexts.billing.application.use_cases.money_setting_audit import (
    RecordMoneySettingChange,
)

_NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


class _Audit:
    def __init__(self, *, fail: bool = False) -> None:
        self.entries: list[Any] = []
        self.fail = fail

    async def append(self, entry: Any) -> None:
        if self.fail:
            raise RuntimeError("audit store down")
        self.entries.append(entry)


@pytest.mark.asyncio
async def test_a_change_appends_one_billing_audit_entry() -> None:
    audit = _Audit()
    use_case = RecordMoneySettingChange(audit=audit, now=lambda: _NOW)

    landed = await use_case.execute(
        academy_id="blno",
        action="academy_timezone_changed",
        actor_id="owner-1",
        before={"timezone": "America/Chicago"},
        after={"timezone": "America/New_York"},
        reason="Settings -> Academy",
    )

    assert landed is True
    [entry] = audit.entries
    assert entry.academy_id == "blno"
    assert entry.action == "academy_timezone_changed"
    assert entry.at == _NOW
    assert entry.before == {"timezone": "America/Chicago"}
    assert entry.after == {"timezone": "America/New_York"}
    assert entry.audit_id.startswith("baud-")


@pytest.mark.asyncio
async def test_no_change_writes_nothing() -> None:
    audit = _Audit()
    use_case = RecordMoneySettingChange(audit=audit)

    await use_case.execute(
        academy_id="blno",
        action="session_fee_changed",
        actor_id="owner-1",
        before={"amount_cents": 6000},
        after={"amount_cents": 6000},
    )

    assert audit.entries == []


@pytest.mark.asyncio
async def test_an_audit_failure_is_reported_not_raised() -> None:
    """The setting already landed; a 500 here would invite a retried write."""
    use_case = RecordMoneySettingChange(audit=_Audit(fail=True))

    landed = await use_case.execute(
        academy_id="blno",
        action="session_fee_changed",
        actor_id="owner-1",
        before={"amount_cents": 6000},
        after={"amount_cents": 7500},
    )

    assert landed is False
