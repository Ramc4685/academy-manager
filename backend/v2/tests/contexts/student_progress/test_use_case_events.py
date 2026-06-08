"""Student progress use cases emit domain events."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from backend.v2.contexts.student_progress.application.use_cases.place_student import (
    PlaceStudentInLevel,
    PlaceStudentInLevelCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.recommend_level_up import (
    RecommendLevelUp,
    RecommendLevelUpCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.record_test_attempt import (
    RecordTestAttempt,
    RecordTestAttemptCommand,
)
from backend.v2.contexts.student_progress.application.use_cases.review_level_up import (
    ReviewLevelUpCommand,
    ReviewLevelUpRecommendation,
)
from backend.v2.contexts.student_progress.application.use_cases.update_skill_status import (
    UpdateSkillStatus,
    UpdateSkillStatusCommand,
)
from backend.v2.contexts.student_progress.domain.models import (
    LevelUpRecommendation,
    SkillCertificate,
    StudentLevelProgress,
    StudentSkillProgress,
)
from backend.v2.contexts.student_progress.domain.models import (
    TestAttempt as StudentTestAttempt,
)
from backend.v2.shared.tenancy import tenant_scope


class _FakeOutbox:
    def __init__(self) -> None:
        self.events: list = []

    async def append(self, event, *, session=None) -> None:
        self.events.append(event)


class _LevelProgressRepo:
    def __init__(self) -> None:
        self.rows: dict[str, StudentLevelProgress] = {}

    async def save(self, progress: StudentLevelProgress) -> None:
        self.rows[progress.progress_id] = progress

    async def get_active(self, student_id: str, program_id: str) -> StudentLevelProgress | None:
        for row in self.rows.values():
            if (
                row.student_id == student_id
                and row.program_id == program_id
                and row.status == "active"
            ):
                return row
        return None

    async def get_by_id(self, progress_id: str) -> StudentLevelProgress | None:
        return self.rows.get(progress_id)

    async def complete(self, progress_id: str, completed_at: object) -> None:
        row = self.rows[progress_id]
        self.rows[progress_id] = row.model_copy(
            update={"status": "completed", "completed_at": completed_at}
        )

    async def list_for_student(self, student_id: str) -> list[StudentLevelProgress]:
        return [row for row in self.rows.values() if row.student_id == student_id]


class _SkillProgressRepo:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], StudentSkillProgress] = {}

    async def save(self, skill_progress: StudentSkillProgress) -> None:
        self.rows[(skill_progress.student_id, skill_progress.skill_id)] = skill_progress

    async def upsert(self, skill_progress: StudentSkillProgress) -> StudentSkillProgress:
        self.rows[(skill_progress.student_id, skill_progress.skill_id)] = skill_progress
        return skill_progress

    async def get(self, student_id: str, skill_id: str) -> StudentSkillProgress | None:
        return self.rows.get((student_id, skill_id))

    async def list_for_student_level(
        self, student_id: str, level_id: str
    ) -> list[StudentSkillProgress]:
        return [
            row
            for row in self.rows.values()
            if row.student_id == student_id and row.level_id == level_id
        ]

    async def list_passed_for_student_level(
        self, student_id: str, level_id: str
    ) -> list[StudentSkillProgress]:
        return [
            row
            for row in await self.list_for_student_level(student_id, level_id)
            if row.status == "PASSED"
        ]


class _TestAttemptRepo:
    def __init__(self) -> None:
        self.rows: list[StudentTestAttempt] = []

    async def save(self, attempt: StudentTestAttempt) -> None:
        self.rows.append(attempt)

    async def list_for_student_skill(
        self, student_id: str, skill_id: str
    ) -> list[StudentTestAttempt]:
        return [
            row for row in self.rows if row.student_id == student_id and row.skill_id == skill_id
        ]

    async def count_for_student_skill(self, student_id: str, skill_id: str) -> int:
        return len(await self.list_for_student_skill(student_id, skill_id))


class _RecommendationRepo:
    def __init__(self) -> None:
        self.rows: dict[str, LevelUpRecommendation] = {}

    async def save(self, rec: LevelUpRecommendation) -> None:
        self.rows[rec.rec_id] = rec

    async def update_status(
        self,
        rec_id: str,
        status: str,
        reviewed_by: str | None,
        reviewed_at: object | None,
        rejection_reason: str | None,
    ) -> None:
        rec = self.rows[rec_id]
        self.rows[rec_id] = rec.model_copy(
            update={
                "status": status,
                "reviewed_by": reviewed_by,
                "reviewed_at": reviewed_at,
                "rejection_reason": rejection_reason,
            }
        )

    async def get(self, rec_id: str) -> LevelUpRecommendation | None:
        return self.rows.get(rec_id)

    async def get_active_for_student(
        self, student_id: str, program_id: str
    ) -> LevelUpRecommendation | None:
        for row in self.rows.values():
            if (
                row.student_id == student_id
                and row.program_id == program_id
                and row.status == "RECOMMENDED"
            ):
                return row
        return None

    async def list_pending(self) -> list[LevelUpRecommendation]:
        return [row for row in self.rows.values() if row.status == "RECOMMENDED"]


class _CertificateRepo:
    def __init__(self) -> None:
        self.rows: list[SkillCertificate] = []

    async def save(self, cert: SkillCertificate) -> None:
        self.rows.append(cert)

    async def list_for_student(self, student_id: str) -> list[SkillCertificate]:
        return [row for row in self.rows if row.student_id == student_id]


class _SkillLookup:
    def __init__(self) -> None:
        self.skills_by_level = {
            "level-1": [
                SimpleNamespace(
                    skill_id="skill-1",
                    is_required=True,
                    pass_threshold_pct=70.0,
                    coach_override_allowed=False,
                ),
                SimpleNamespace(
                    skill_id="skill-2",
                    is_required=True,
                    pass_threshold_pct=70.0,
                    coach_override_allowed=False,
                ),
            ],
            "level-2": [
                SimpleNamespace(
                    skill_id="skill-3",
                    is_required=True,
                    pass_threshold_pct=70.0,
                    coach_override_allowed=False,
                )
            ],
        }
        self.levels = {
            "level-1": SimpleNamespace(level_id="level-1", sequence=1),
            "level-2": SimpleNamespace(level_id="level-2", sequence=2),
        }

    async def get_skill(self, skill_id: str) -> object | None:
        for skills in self.skills_by_level.values():
            for skill in skills:
                if skill.skill_id == skill_id:
                    return skill
        return None

    async def get_level(self, level_id: str) -> object | None:
        return self.levels.get(level_id)

    async def list_skills_for_level(self, level_id: str) -> list[object]:
        return list(self.skills_by_level.get(level_id, []))

    async def get_next_level(self, program_id: str, current_sequence: int) -> object | None:
        for level in self.levels.values():
            if level.sequence == current_sequence + 1:
                return level
        return None


_NOW = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)


def _active_progress(progress_id: str = "progress-1") -> StudentLevelProgress:
    return StudentLevelProgress(
        progress_id=progress_id,
        academy_id="academy-1",
        student_id="student-1",
        program_id="program-1",
        level_id="level-1",
        status="active",
        started_at=_NOW,
        completed_at=None,
        created_at=_NOW,
    )


def _skill_progress(skill_id: str, status: str = "NOT_STARTED") -> StudentSkillProgress:
    return StudentSkillProgress(
        skill_progress_id=f"sp-{skill_id}",
        academy_id="academy-1",
        student_id="student-1",
        skill_id=skill_id,
        level_id="level-1",
        program_id="program-1",
        status=status,
        introduced_at=None,
        last_updated_at=_NOW,
        last_updated_by="coach-1",
    )


@pytest.mark.asyncio
async def test_place_student_emits_student_placed_event() -> None:
    level_progress = _LevelProgressRepo()
    skill_progress = _SkillProgressRepo()
    outbox = _FakeOutbox()
    use_case = PlaceStudentInLevel(
        level_progress=level_progress,
        skill_progress=skill_progress,
        skill_lookup=_SkillLookup(),
        outbox=outbox,
    )

    with tenant_scope("academy-1"):
        result = await use_case.execute(
            PlaceStudentInLevelCommand(
                student_id="student-1",
                program_id="program-1",
                level_id="level-1",
                placed_by="admin-1",
            )
        )

    assert [event.name for event in outbox.events] == ["StudentProgress.StudentPlacedInLevel"]
    event = outbox.events[0]
    assert event.aggregate_id == result.progress_id
    assert event.academy_id == "academy-1"
    assert event.payload.student_id == "student-1"
    assert event.payload.program_id == "program-1"
    assert event.payload.level_id == "level-1"
    assert event.payload.progress_id == result.progress_id
    assert event.payload.placed_by == "admin-1"
    assert event.payload.reason == "pathway_placement"


@pytest.mark.asyncio
async def test_update_skill_status_emits_status_updated_event() -> None:
    level_progress = _LevelProgressRepo()
    await level_progress.save(_active_progress())
    skill_progress = _SkillProgressRepo()
    await skill_progress.upsert(_skill_progress("skill-1", "NOT_STARTED"))
    outbox = _FakeOutbox()
    use_case = UpdateSkillStatus(
        level_progress=level_progress,
        skill_progress=skill_progress,
        outbox=outbox,
    )

    with tenant_scope("academy-1"):
        result = await use_case.execute(
            UpdateSkillStatusCommand(
                student_id="student-1",
                skill_id="skill-1",
                level_id="level-1",
                program_id="program-1",
                new_status="LEARNING",
                updated_by="coach-1",
            )
        )

    assert [event.name for event in outbox.events] == ["StudentProgress.SkillStatusUpdated"]
    event = outbox.events[0]
    assert event.aggregate_id == result.skill_progress_id
    assert event.academy_id == "academy-1"
    assert event.payload.student_id == "student-1"
    assert event.payload.skill_id == "skill-1"
    assert event.payload.level_id == "level-1"
    assert event.payload.old_status == "NOT_STARTED"
    assert event.payload.new_status == "LEARNING"
    assert event.payload.updated_by == "coach-1"


@pytest.mark.asyncio
async def test_record_test_attempt_emits_attempt_event_even_when_not_passed() -> None:
    level_progress = _LevelProgressRepo()
    await level_progress.save(_active_progress())
    skill_progress = _SkillProgressRepo()
    await skill_progress.upsert(_skill_progress("skill-1", "TEST_READY"))
    outbox = _FakeOutbox()
    use_case = RecordTestAttempt(
        level_progress=level_progress,
        skill_progress=skill_progress,
        test_attempts=_TestAttemptRepo(),
        skill_lookup=_SkillLookup(),
        outbox=outbox,
    )

    with tenant_scope("academy-1"):
        result = await use_case.execute(
            RecordTestAttemptCommand(
                student_id="student-1",
                skill_id="skill-1",
                level_id="level-1",
                program_id="program-1",
                coach_id="coach-1",
                session_id="session-1",
                attempts_count=10,
                success_count=4,
            )
        )

    assert [event.name for event in outbox.events] == ["StudentProgress.SkillTestAttempted"]
    event = outbox.events[0]
    assert event.aggregate_id == result.attempt_id
    assert event.academy_id == "academy-1"
    assert event.payload.attempt_id == result.attempt_id
    assert event.payload.student_id == "student-1"
    assert event.payload.skill_id == "skill-1"
    assert event.payload.level_id == "level-1"
    assert event.payload.program_id == "program-1"
    assert event.payload.coach_id == "coach-1"
    assert event.payload.attempts_count == 10
    assert event.payload.success_count == 4
    assert event.payload.passed is False


@pytest.mark.asyncio
async def test_record_test_attempt_emits_pass_and_completion_events_when_level_completed() -> None:
    level_progress = _LevelProgressRepo()
    await level_progress.save(_active_progress("progress-completing"))
    skill_progress = _SkillProgressRepo()
    await skill_progress.upsert(_skill_progress("skill-1", "TEST_READY"))
    await skill_progress.upsert(_skill_progress("skill-2", "PASSED"))
    outbox = _FakeOutbox()
    use_case = RecordTestAttempt(
        level_progress=level_progress,
        skill_progress=skill_progress,
        test_attempts=_TestAttemptRepo(),
        skill_lookup=_SkillLookup(),
        outbox=outbox,
    )

    with tenant_scope("academy-1"):
        result = await use_case.execute(
            RecordTestAttemptCommand(
                student_id="student-1",
                skill_id="skill-1",
                level_id="level-1",
                program_id="program-1",
                coach_id="coach-1",
                attempts_count=10,
                success_count=8,
            )
        )

    assert [event.name for event in outbox.events] == [
        "StudentProgress.SkillTestAttempted",
        "StudentProgress.SkillPassed",
        "StudentProgress.LevelCompleted",
    ]
    attempted, passed, completed = outbox.events
    assert attempted.aggregate_id == result.attempt_id
    assert passed.aggregate_id == result.attempt_id
    assert passed.payload.attempt_id == result.attempt_id
    assert passed.payload.skill_id == "skill-1"
    assert completed.aggregate_id == "progress-completing"
    assert completed.payload.progress_id == "progress-completing"
    assert completed.payload.level_id == "level-1"


@pytest.mark.asyncio
async def test_recommend_level_up_emits_recommended_event() -> None:
    level_progress = _LevelProgressRepo()
    await level_progress.save(_active_progress())
    skill_progress = _SkillProgressRepo()
    await skill_progress.upsert(_skill_progress("skill-1", "PASSED"))
    await skill_progress.upsert(_skill_progress("skill-2", "PASSED"))
    recommendations = _RecommendationRepo()
    outbox = _FakeOutbox()
    use_case = RecommendLevelUp(
        level_progress=level_progress,
        skill_progress=skill_progress,
        recommendations=recommendations,
        skill_lookup=_SkillLookup(),
        outbox=outbox,
    )

    with tenant_scope("academy-1"):
        result = await use_case.execute(
            RecommendLevelUpCommand(
                student_id="student-1",
                program_id="program-1",
                recommended_by="coach-1",
            )
        )

    assert [event.name for event in outbox.events] == ["StudentProgress.LevelUpRecommended"]
    event = outbox.events[0]
    assert event.aggregate_id == result.rec_id
    assert event.academy_id == "academy-1"
    assert event.payload.rec_id == result.rec_id
    assert event.payload.student_id == "student-1"
    assert event.payload.from_level_id == "level-1"
    assert event.payload.to_level_id == "level-2"
    assert event.payload.program_id == "program-1"
    assert event.payload.recommended_by == "coach-1"


@pytest.mark.asyncio
async def test_review_level_up_approve_emits_leveled_up_and_certificate_events() -> None:
    level_progress = _LevelProgressRepo()
    await level_progress.save(_active_progress())
    skill_progress = _SkillProgressRepo()
    recommendations = _RecommendationRepo()
    rec = LevelUpRecommendation(
        rec_id="rec-1",
        academy_id="academy-1",
        student_id="student-1",
        from_level_id="level-1",
        to_level_id="level-2",
        program_id="program-1",
        status="RECOMMENDED",
        recommended_by="coach-1",
        recommended_at=_NOW,
    )
    await recommendations.save(rec)
    certs = _CertificateRepo()
    outbox = _FakeOutbox()
    use_case = ReviewLevelUpRecommendation(
        recommendations=recommendations,
        level_progress=level_progress,
        skill_progress=skill_progress,
        certificates=certs,
        skill_lookup=_SkillLookup(),
        outbox=outbox,
    )

    with tenant_scope("academy-1"):
        result = await use_case.execute(
            ReviewLevelUpCommand(
                rec_id="rec-1",
                action="approve",
                reviewed_by="admin-1",
                student_name="Student One",
                level_name="Level One",
                program_name="Program One",
                level_sequence=1,
            )
        )

    assert [event.name for event in outbox.events] == [
        "StudentProgress.StudentLeveledUp",
        "StudentProgress.CertificateIssued",
    ]
    leveled_up, certificate_issued = outbox.events
    assert result.cert_id is not None
    assert leveled_up.aggregate_id == rec.rec_id
    assert leveled_up.academy_id == "academy-1"
    assert leveled_up.payload.student_id == "student-1"
    assert leveled_up.payload.from_level_id == "level-1"
    assert leveled_up.payload.to_level_id == "level-2"
    assert leveled_up.payload.program_id == "program-1"
    assert leveled_up.payload.cert_id == result.cert_id
    assert leveled_up.payload.new_progress_id is not None
    assert certificate_issued.aggregate_id == result.cert_id
    assert certificate_issued.payload.cert_id == result.cert_id
    assert certificate_issued.payload.student_id == "student-1"
    assert certificate_issued.payload.level_id == "level-1"
    assert certificate_issued.payload.program_id == "program-1"
    assert certificate_issued.payload.issued_by == "admin-1"
