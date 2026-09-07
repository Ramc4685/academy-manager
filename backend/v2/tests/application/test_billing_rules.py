"""Billing rules: the assembler and the audited write.

Spec: ``docs/superpowers/specs/2026-09-07-billing-rules-design.md`` SS6.

The load-bearing test here is ``test_retry_row_follows_the_ladder_constant``:
it changes ``DUNNING_SCHEDULE_DAYS`` and asserts the page changes with it. If
someone re-types the ladder as a literal in the view, that test fails and the
panel cannot silently drift away from the worker.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.contexts.billing.application.use_cases import billing_rules as rules
from backend.v2.contexts.billing.application.use_cases.billing_rules import (
    BILLING_RULE_BOUNDS,
    EDITABLE_RULE_KEYS,
    LATE_FEE_NOTE,
    BillingRulesPartialWriteError,
    BillingRulesValidationError,
    BuildBillingRulesView,
    UpdateBillingRules,
    UpdateBillingRulesCommand,
)
from backend.v2.contexts.billing.application.use_cases.billing_settings_admin import (
    SetInvoiceScheduleCommand,
)
from backend.v2.contexts.billing.domain.billing_audit import BillingAuditEntry


@dataclass
class _Schedule:
    billing_day: int
    invoice_due_days: int


@dataclass
class _Fees:
    late_fee_cents: int | None
    grace_days: int | None


@dataclass
class _Policy:
    cancellation_minimum_notice_days: int
    cancellation_fee_cents: int


class _FakeSchedule:
    def __init__(self, billing_day: int = 1, invoice_due_days: int = 7) -> None:
        self.current = _Schedule(billing_day, invoice_due_days)
        self.commands: list[SetInvoiceScheduleCommand] = []
        self.fail = False

    async def read(self) -> _Schedule:
        return self.current

    async def write(self, cmd: SetInvoiceScheduleCommand) -> _Schedule:
        if self.fail:
            raise RuntimeError("schedule store down")
        self.commands.append(cmd)
        self.current = _Schedule(cmd.billing_day, cmd.invoice_due_days)
        return self.current


class _FakeFees:
    def __init__(self, late_fee_cents: int | None = 0, grace_days: int | None = 0) -> None:
        self.current = _Fees(late_fee_cents, grace_days)
        self.writes: list[dict[str, Any]] = []
        self.fail = False

    async def read(self, academy_id: str) -> _Fees:
        assert academy_id
        return self.current

    async def write(self, academy_id: str, fields: dict[str, Any]) -> _Fees:
        if self.fail:
            raise RuntimeError("fees store down")
        self.writes.append(fields)
        self.current = _Fees(
            fields.get("late_fee_cents", self.current.late_fee_cents),
            fields.get("grace_days", self.current.grace_days),
        )
        return self.current


class _FakePolicy:
    def __init__(self, notice_days: int = 14, fee_cents: int = 0) -> None:
        self.current = _Policy(notice_days, fee_cents)
        self.writes: list[tuple[int, int]] = []
        self.fail = False

    async def read(self) -> _Policy:
        return self.current

    async def write(
        self, *, cancellation_minimum_notice_days: int, cancellation_fee_cents: int
    ) -> _Policy:
        if self.fail:
            raise RuntimeError("policy store down")
        self.writes.append((cancellation_minimum_notice_days, cancellation_fee_cents))
        self.current = _Policy(cancellation_minimum_notice_days, cancellation_fee_cents)
        return self.current


class _Reader:
    def __init__(self, fn: Any) -> None:
        self.execute = fn


class _FakeAudit:
    def __init__(self) -> None:
        self.entries: list[BillingAuditEntry] = []

    async def append(self, entry: BillingAuditEntry) -> None:
        self.entries.append(entry)


def _build(schedule: _FakeSchedule, fees: _FakeFees, policy: _FakePolicy) -> BuildBillingRulesView:
    return BuildBillingRulesView(
        schedule=_Reader(schedule.read),
        fees=_Reader(fees.read),
        cancellation=_Reader(policy.read),
    )


def _update(
    schedule: _FakeSchedule,
    fees: _FakeFees,
    policy: _FakePolicy,
    audit: _FakeAudit | None = None,
) -> UpdateBillingRules:
    return UpdateBillingRules(
        schedule_reader=_Reader(schedule.read),
        schedule_writer=_Reader(schedule.write),
        fees_reader=_Reader(fees.read),
        fees_writer=_Reader(fees.write),
        cancellation_reader=_Reader(policy.read),
        cancellation_writer=_Reader(policy.write),
        audit=audit,
        clock=lambda: datetime(2026, 9, 7, tzinfo=UTC),
    )


# --- The assembler -----------------------------------------------------


@pytest.mark.asyncio
async def test_view_has_the_four_boxes_in_spec_order() -> None:
    view = await _build(_FakeSchedule(), _FakeFees(), _FakePolicy()).execute("acad-1")
    assert [group.key for group in view.groups] == [
        "monthly_invoicing",
        "late_payments",
        "leaving_and_pausing",
        "parent_messages",
    ]


@pytest.mark.asyncio
async def test_editable_rows_match_the_write_model_exactly() -> None:
    view = await _build(_FakeSchedule(), _FakeFees(), _FakePolicy()).execute("acad-1")
    assert sorted(view.editable_keys) == sorted(EDITABLE_RULE_KEYS)
    assert sorted(EDITABLE_RULE_KEYS) == sorted(
        field
        for field in UpdateBillingRulesCommand.model_fields
        if field not in {"actor_id", "reason"}
    )


@pytest.mark.asyncio
async def test_editable_rows_carry_their_stored_value_and_bounds() -> None:
    view = await _build(
        _FakeSchedule(billing_day=12, invoice_due_days=3),
        _FakeFees(late_fee_cents=2500, grace_days=5),
        _FakePolicy(notice_days=21, fee_cents=1500),
    ).execute("acad-1")
    assert view.row("billing_day").value == 12
    assert view.row("invoice_due_days").value == 3
    assert view.row("grace_days").value == 5
    assert view.row("late_fee_cents").value == 2500
    assert view.row("late_fee_cents").unit == "cents"
    assert view.row("cancellation_minimum_notice_days").value == 21
    assert view.row("cancellation_fee_cents").value == 1500
    for key, (low, high) in BILLING_RULE_BOUNDS.items():
        assert (view.row(key).min_value, view.row(key).max_value) == (low, high)


@pytest.mark.asyncio
async def test_fixed_rows_are_not_editable_and_state_a_value() -> None:
    view = await _build(_FakeSchedule(), _FakeFees(), _FakePolicy()).execute("acad-1")
    fixed = [row for group in view.groups for row in group.rows if not row.editable]
    assert len(fixed) == 9
    for row in fixed:
        assert row.display
        assert row.value is None
        assert row.min_value is None


@pytest.mark.asyncio
async def test_late_payments_box_carries_the_not_applied_note() -> None:
    view = await _build(_FakeSchedule(), _FakeFees(), _FakePolicy()).execute("acad-1")
    late = next(group for group in view.groups if group.key == "late_payments")
    assert late.note == LATE_FEE_NOTE
    assert "Not applied automatically yet" in LATE_FEE_NOTE


@pytest.mark.asyncio
async def test_charge_hour_row_follows_the_domain_constant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = await _build(_FakeSchedule(), _FakeFees(), _FakePolicy()).execute("acad-1")
    assert view.row("autopay_charge_time").display == "09:00 academy time on the due date"

    monkeypatch.setattr(rules, "FIRST_ATTEMPT_LOCAL_HOUR", 6)
    drifted = await _build(_FakeSchedule(), _FakeFees(), _FakePolicy()).execute("acad-1")
    assert drifted.row("autopay_charge_time").display == "06:00 academy time on the due date"


@pytest.mark.asyncio
async def test_retry_row_follows_the_ladder_constant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Change the ladder, and the page changes. This is the anti-drift test."""
    view = await _build(_FakeSchedule(), _FakeFees(), _FakePolicy()).execute("acad-1")
    assert view.row("retry_schedule").display == (
        "same day, then 3, 5 and 7 days later, then autopay switches off"
    )
    assert "4 attempts in total" in (view.row("retry_schedule").detail or "")

    monkeypatch.setattr(rules, "DUNNING_SCHEDULE_DAYS", (0, 2, 4))
    monkeypatch.setattr(rules, "MAX_DUNNING_ATTEMPTS", 3)
    drifted = await _build(_FakeSchedule(), _FakeFees(), _FakePolicy()).execute("acad-1")
    assert drifted.row("retry_schedule").display == (
        "same day, then 2 and 4 days later, then autopay switches off"
    )
    assert "3 attempts in total" in (drifted.row("retry_schedule").detail or "")


@pytest.mark.asyncio
async def test_join_mid_month_row_names_the_proration_policy_version() -> None:
    view = await _build(_FakeSchedule(), _FakeFees(), _FakePolicy()).execute("acad-1")
    assert "first-month-proration-v1" in (view.row("join_mid_month").detail or "")
    assert rules.proration_policy_version() == "first-month-proration-v1"


# --- The write ---------------------------------------------------------


@pytest.mark.asyncio
async def test_only_changed_fields_are_written_and_audited() -> None:
    schedule, fees, policy = _FakeSchedule(1, 7), _FakeFees(0, 0), _FakePolicy(14, 0)
    audit = _FakeAudit()
    result = await _update(schedule, fees, policy, audit).execute(
        "acad-1",
        UpdateBillingRulesCommand(
            billing_day=1,  # unchanged
            invoice_due_days=10,  # changed
            grace_days=0,  # unchanged
            late_fee_cents=2500,  # changed
            actor_id="user-1",
            reason="autumn review",
        ),
    )
    assert set(result.changed_fields) == {"invoice_due_days", "late_fee_cents"}
    assert fees.writes == [{"late_fee_cents": 2500}]
    assert policy.writes == []
    assert len(audit.entries) == 1
    entry = audit.entries[0]
    assert entry.action == "billing_rules_changed"
    assert entry.actor_id == "user-1"
    assert entry.reason == "autumn review"
    assert entry.before == {"invoice_due_days": 7, "late_fee_cents": 0}
    assert entry.after == {"invoice_due_days": 10, "late_fee_cents": 2500}


@pytest.mark.asyncio
async def test_schedule_write_carries_the_unchanged_half_through() -> None:
    schedule = _FakeSchedule(1, 7)
    await _update(schedule, _FakeFees(), _FakePolicy()).execute(
        "acad-1", UpdateBillingRulesCommand(billing_day=15, actor_id="user-1")
    )
    assert schedule.commands[0].billing_day == 15
    assert schedule.commands[0].invoice_due_days == 7


@pytest.mark.asyncio
async def test_policy_write_carries_the_unchanged_half_through() -> None:
    policy = _FakePolicy(14, 500)
    await _update(_FakeSchedule(), _FakeFees(), policy).execute(
        "acad-1",
        UpdateBillingRulesCommand(cancellation_fee_cents=900, actor_id="user-1"),
    )
    assert policy.writes == [(14, 900)]


@pytest.mark.asyncio
async def test_a_no_op_request_writes_nothing_at_all() -> None:
    schedule, fees, policy = _FakeSchedule(4, 7), _FakeFees(1000, 3), _FakePolicy(14, 500)
    audit = _FakeAudit()
    result = await _update(schedule, fees, policy, audit).execute(
        "acad-1",
        UpdateBillingRulesCommand(
            billing_day=4,
            invoice_due_days=7,
            grace_days=3,
            late_fee_cents=1000,
            cancellation_minimum_notice_days=14,
            cancellation_fee_cents=500,
            actor_id="user-1",
        ),
    )
    assert result.changed_fields == ()
    assert schedule.commands == []
    assert fees.writes == []
    assert policy.writes == []
    assert audit.entries == []


@pytest.mark.asyncio
async def test_an_empty_request_writes_nothing_at_all() -> None:
    schedule, fees, policy = _FakeSchedule(), _FakeFees(), _FakePolicy()
    audit = _FakeAudit()
    result = await _update(schedule, fees, policy, audit).execute(
        "acad-1", UpdateBillingRulesCommand(actor_id="user-1")
    )
    assert result.changed_fields == ()
    assert audit.entries == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("billing_day", 0),
        ("billing_day", 29),
        ("invoice_due_days", -1),
        ("invoice_due_days", 61),
        ("grace_days", -1),
        ("grace_days", 61),
        ("late_fee_cents", -1),
        ("late_fee_cents", 100_001),
        ("cancellation_minimum_notice_days", -1),
        ("cancellation_minimum_notice_days", 91),
        ("cancellation_fee_cents", -1),
        ("cancellation_fee_cents", 100_001),
    ],
)
@pytest.mark.asyncio
async def test_every_bound_is_rejected(field: str, value: int) -> None:
    schedule, fees, policy = _FakeSchedule(), _FakeFees(), _FakePolicy()
    audit = _FakeAudit()
    with pytest.raises(BillingRulesValidationError) as excinfo:
        await _update(schedule, fees, policy, audit).execute(
            "acad-1", UpdateBillingRulesCommand(actor_id="user-1", **{field: value})
        )
    assert excinfo.value.field == field
    assert schedule.commands == []
    assert fees.writes == []
    assert policy.writes == []
    assert audit.entries == []


@pytest.mark.asyncio
async def test_an_invalid_field_is_rejected_before_any_store_is_touched() -> None:
    """A bad late fee must not leave a saved billing day behind it (SS4.2)."""
    schedule, fees, policy = _FakeSchedule(1, 7), _FakeFees(0, 0), _FakePolicy()
    audit = _FakeAudit()
    with pytest.raises(BillingRulesValidationError) as excinfo:
        await _update(schedule, fees, policy, audit).execute(
            "acad-1",
            UpdateBillingRulesCommand(billing_day=15, late_fee_cents=-1, actor_id="user-1"),
        )
    assert excinfo.value.field == "late_fee_cents"
    assert schedule.commands == []
    assert schedule.current.billing_day == 1
    assert audit.entries == []


@pytest.mark.asyncio
async def test_a_partial_failure_audits_only_what_landed() -> None:
    schedule, fees, policy = _FakeSchedule(1, 7), _FakeFees(0, 0), _FakePolicy(14, 0)
    fees.fail = True
    audit = _FakeAudit()
    with pytest.raises(BillingRulesPartialWriteError) as excinfo:
        await _update(schedule, fees, policy, audit).execute(
            "acad-1",
            UpdateBillingRulesCommand(
                billing_day=15,
                late_fee_cents=2500,
                cancellation_fee_cents=900,
                actor_id="user-1",
            ),
        )
    assert excinfo.value.applied_fields == ("billing_day",)
    assert len(audit.entries) == 1
    assert audit.entries[0].before == {"billing_day": 1}
    assert audit.entries[0].after == {"billing_day": 15}
    # The cancellation policy is written after the fees, so it never ran.
    assert policy.writes == []


@pytest.mark.asyncio
async def test_a_failure_on_the_first_store_writes_no_audit_entry() -> None:
    schedule, fees, policy = _FakeSchedule(1, 7), _FakeFees(), _FakePolicy()
    schedule.fail = True
    audit = _FakeAudit()
    with pytest.raises(BillingRulesPartialWriteError) as excinfo:
        await _update(schedule, fees, policy, audit).execute(
            "acad-1", UpdateBillingRulesCommand(billing_day=15, actor_id="user-1")
        )
    assert excinfo.value.applied_fields == ()
    assert audit.entries == []


@pytest.mark.asyncio
async def test_a_previously_unset_fee_counts_as_a_change() -> None:
    fees = _FakeFees(late_fee_cents=None, grace_days=None)
    audit = _FakeAudit()
    result = await _update(_FakeSchedule(), fees, _FakePolicy(), audit).execute(
        "acad-1", UpdateBillingRulesCommand(grace_days=0, actor_id="user-1")
    )
    assert result.changed_fields == ("grace_days",)
    assert audit.entries[0].before == {"grace_days": None}
    assert audit.entries[0].after == {"grace_days": 0}
