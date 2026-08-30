"""RecordTestAttempt validation and idempotency (issue #524).

- success_count must never exceed attempts_count (a 500% score would
  force-pass the skill past pass_threshold_pct and the override gate).
- Retries carrying the same mutation_id return the original result instead
  of inserting duplicate TestAttempt rows and re-emitting progress events.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from backend.v2.contexts.student_progress.application.use_cases.record_test_attempt import (
    RecordTestAttempt,
    RecordTestAttemptCommand,
)
from backend.v2.shared.tenancy import tenant_scope
from backend.v2.tests.contexts.student_progress.test_use_case_events import (
    _active_progress,
    _FakeOutbox,
    _LevelProgressRepo,
    _skill_progress,
    _SkillLookup,
    _SkillProgressRepo,
    _TestAttemptRepo,
)


class _MemoryIdempotencyStore:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    async def get(self, key: str) -> dict[str, Any] | None:
        return self.rows.get(key)

    async def put(self, key: str, value: dict[str, Any]) -> None:
        self.rows[key] = value


def _command(**overrides: Any) -> RecordTestAttemptCommand:
    base: dict[str, Any] = {
        "student_id": "student-1",
        "skill_id": "skill-1",
        "level_id": "level-1",
        "program_id": "program-1",
        "coach_id": "coach-1",
        "attempts_count": 10,
        "success_count": 8,
    }
    base.update(overrides)
    return RecordTestAttemptCommand(**base)


def _use_case(
    *,
    attempts: _TestAttemptRepo,
    outbox: _FakeOutbox,
    store: _MemoryIdempotencyStore | None,
) -> RecordTestAttempt:
    level_progress = _LevelProgressRepo()
    level_progress.rows["progress-1"] = _active_progress()
    skill_progress = _SkillProgressRepo()
    prog = _skill_progress("skill-1", "TEST_READY")
    skill_progress.rows[(prog.student_id, prog.skill_id)] = prog
    return RecordTestAttempt(
        level_progress=level_progress,
        skill_progress=skill_progress,
        test_attempts=attempts,
        skill_lookup=_SkillLookup(),
        outbox=outbox,
        idempotency_store=store,
    )


def test_command_rejects_success_count_above_attempts_count() -> None:
    with pytest.raises(ValidationError, match="success_count cannot exceed attempts_count"):
        _command(attempts_count=1, success_count=5)


def test_command_allows_success_count_equal_to_attempts_count() -> None:
    cmd = _command(attempts_count=5, success_count=5)
    assert cmd.success_count == 5


@pytest.mark.asyncio
async def test_retry_with_same_mutation_id_returns_original_result() -> None:
    attempts = _TestAttemptRepo()
    outbox = _FakeOutbox()
    use_case = _use_case(attempts=attempts, outbox=outbox, store=_MemoryIdempotencyStore())

    with tenant_scope("academy-1"):
        first = await use_case.execute(_command(mutation_id="mut-1"))
        second = await use_case.execute(_command(mutation_id="mut-1"))

    assert second == first
    assert len(attempts.rows) == 1
    # Events were emitted exactly once (SkillTestAttempted + SkillPassed).
    assert [event.name for event in outbox.events] == [
        "StudentProgress.SkillTestAttempted",
        "StudentProgress.SkillPassed",
    ]


@pytest.mark.asyncio
async def test_distinct_mutation_ids_record_distinct_attempts() -> None:
    attempts = _TestAttemptRepo()
    outbox = _FakeOutbox()
    use_case = _use_case(attempts=attempts, outbox=outbox, store=_MemoryIdempotencyStore())

    with tenant_scope("academy-1"):
        first = await use_case.execute(_command(mutation_id="mut-1"))
        second = await use_case.execute(_command(mutation_id="mut-2"))

    assert first.attempt_id != second.attempt_id
    assert len(attempts.rows) == 2


@pytest.mark.asyncio
async def test_missing_mutation_id_still_records_attempt() -> None:
    attempts = _TestAttemptRepo()
    outbox = _FakeOutbox()
    use_case = _use_case(attempts=attempts, outbox=outbox, store=_MemoryIdempotencyStore())

    with tenant_scope("academy-1"):
        result = await use_case.execute(_command())

    assert result.attempt_id
    assert len(attempts.rows) == 1
