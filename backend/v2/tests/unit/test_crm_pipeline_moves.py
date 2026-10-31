"""MoveCardOnPipeline and the stage-skip guard (People CRM L3a, spec §3.4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.crm.application.use_cases.pipeline_moves import (
    MoveCardCommand,
    MoveCardOnPipeline,
)
from backend.v2.contexts.crm.domain.errors import ContactNotFound, PipelineMoveNotAllowed
from backend.v2.contexts.crm.domain.models import CrmContact, PipelineOverride
from backend.v2.contexts.crm.domain.pipeline import (
    PIPELINE_COLUMNS,
    current_column,
    refuse_move,
)
from backend.v2.shared.tenancy import tenant_scope
from backend.v2.tests.fixtures.trial_outcome_fakes import FakeContactStore

A = "acad-a"
B = "acad-b"
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def _contact(
    contact_id: str = "c-1",
    *,
    academy: str = A,
    status: str = "lead",
    override: str | None = None,
) -> CrmContact:
    return CrmContact(
        contact_id=contact_id,
        academy_id=academy,
        name="Sample Parent",
        phone_digits="5550102030",
        source="whatsapp_or_phone",
        pipeline_status=status,  # type: ignore[arg-type]
        pipeline_override=(
            PipelineOverride(column=override, set_by="staff-0", set_at=NOW - timedelta(days=1))
            if override
            else None
        ),
        created_at=NOW - timedelta(days=2),
        updated_at=NOW - timedelta(days=2),
    )


def _move(store: FakeContactStore) -> MoveCardOnPipeline:
    return MoveCardOnPipeline(store, clock=lambda: NOW)


def test_columns_are_the_spec_board() -> None:
    assert PIPELINE_COLUMNS == ("inquiry", "trial_booked", "trial_done", "registered", "enrolled")


def test_current_column_follows_stage_then_override_then_enrolled() -> None:
    assert current_column(_contact(status="lead")) == "inquiry"
    assert current_column(_contact(status="trial")) == "trial_booked"
    assert current_column(_contact(status="lead", override="trial_done")) == "trial_done"
    # The system's enrolled beats any stale override.
    assert current_column(_contact(status="enrolled", override="trial_done")) == "enrolled"


@pytest.mark.parametrize(
    ("src", "dst", "reason"),
    [
        ("inquiry", "trial_booked", None),
        ("inquiry", "trial_done", "stage_skip"),
        ("inquiry", "registered", "stage_skip"),
        ("trial_done", "registered", None),
        ("registered", "inquiry", None),  # back any number of columns
        ("registered", "enrolled", "needs_system_write"),
        ("inquiry", "won", "unknown_column"),
    ],
)
def test_stage_skip_guard(src: str, dst: str, reason: str | None) -> None:
    assert refuse_move(src, dst, enrolled=False) == reason


def test_enrolled_contact_never_moves() -> None:
    assert refuse_move("enrolled", "registered", enrolled=True) == "contact_enrolled"


async def test_move_writes_override_with_author_and_time() -> None:
    store = FakeContactStore(_contact())
    with tenant_scope(A):
        result = await _move(store).execute(
            MoveCardCommand(contact_id="c-1", to_column="trial_booked", actor_id="staff-1")
        )
    moved = result.contact
    assert result.column == "trial_booked"
    assert moved.pipeline_override == PipelineOverride(
        column="trial_booked", set_by="staff-1", set_at=NOW
    )
    assert moved.updated_at == NOW
    assert moved.pipeline_status == "lead"  # the stage itself is not rewritten


async def test_forward_skip_is_refused_and_nothing_written() -> None:
    store = FakeContactStore(_contact())
    with tenant_scope(A), pytest.raises(PipelineMoveNotAllowed) as err:
        await _move(store).execute(
            MoveCardCommand(contact_id="c-1", to_column="registered", actor_id="staff-1")
        )
    assert err.value.details["reason"] == "stage_skip"
    assert store.writes == 0


async def test_steps_forward_one_at_a_time_from_the_override() -> None:
    store = FakeContactStore(_contact(override="trial_booked"))
    with tenant_scope(A):
        result = await _move(store).execute(
            MoveCardCommand(contact_id="c-1", to_column="trial_done", actor_id="staff-1")
        )
    assert current_column(result.contact) == result.column == "trial_done"


async def test_move_to_current_column_is_a_no_op() -> None:
    store = FakeContactStore(_contact(override="trial_done"))
    with tenant_scope(A):
        same = (
            await _move(store).execute(
                MoveCardCommand(contact_id="c-1", to_column="trial_done", actor_id="staff-2")
            )
        ).contact
    assert same.pipeline_override is not None and same.pipeline_override.set_by == "staff-0"
    assert store.writes == 0


async def test_enrolled_contact_is_refused() -> None:
    store = FakeContactStore(_contact(status="enrolled"))
    with tenant_scope(A), pytest.raises(PipelineMoveNotAllowed) as err:
        await _move(store).execute(
            MoveCardCommand(contact_id="c-1", to_column="registered", actor_id="staff-1")
        )
    assert err.value.details["reason"] == "contact_enrolled"


async def test_other_academy_contact_is_not_found() -> None:
    store = FakeContactStore(_contact(academy=B))
    with tenant_scope(A), pytest.raises(ContactNotFound):
        await _move(store).execute(
            MoveCardCommand(contact_id="c-1", to_column="trial_booked", actor_id="staff-1")
        )


async def test_a_concurrent_move_makes_this_one_fail_not_overwrite() -> None:
    class _MovedMeanwhile(FakeContactStore):
        async def get(self, contact_id: str) -> CrmContact | None:
            row = await super().get(contact_id)
            if self.writes == 0:
                key = (A, contact_id)
                self.rows[key] = self.rows[key].model_copy(
                    update={
                        "pipeline_override": PipelineOverride(
                            column="trial_booked", set_by="staff-9", set_at=NOW
                        )
                    }
                )
            return row

    store = _MovedMeanwhile(_contact())
    with tenant_scope(A), pytest.raises(PipelineMoveNotAllowed) as err:
        await _move(store).execute(
            MoveCardCommand(contact_id="c-1", to_column="trial_booked", actor_id="staff-1")
        )
    assert err.value.details["reason"] == "changed"
    assert store.rows[(A, "c-1")].pipeline_override.set_by == "staff-9"  # type: ignore[union-attr]
