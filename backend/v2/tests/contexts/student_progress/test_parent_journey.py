"""GetParentJourney + the pace estimate behind the parent progress page."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from backend.v2.contexts.student_progress.application.use_cases.get_parent_journey import (
    GetParentJourney,
)
from backend.v2.contexts.student_progress.domain.logic import estimate_weeks_to_next_level
from backend.v2.contexts.student_progress.domain.models import (
    SkillCertificate,
    StudentLevelProgress,
    StudentSkillProgress,
    TestAttempt,
)

NOW = datetime(2026, 10, 31, 18, 0, tzinfo=UTC)
STUDENT = "st-1"
PROGRAM = "prog-1"


# --- pace -----------------------------------------------------------------


def test_pace_from_recent_passes() -> None:
    # 4 passes over 4 weeks = 1/week; 5 left -> 5 weeks.
    dates = [NOW - timedelta(weeks=w) for w in (0, 1, 2, 4)]
    assert estimate_weeks_to_next_level(dates, 5, NOW) == 5


@pytest.mark.parametrize(
    ("dates", "remaining"),
    [
        ([NOW - timedelta(days=d) for d in (1, 3)], 4),  # too few passes
        ([NOW - timedelta(hours=h) for h in (1, 2, 3, 4)], 4),  # one-day backfill
        ([NOW - timedelta(weeks=w) for w in (10, 11, 12)], 4),  # outside the window
        ([NOW - timedelta(weeks=w) for w in (0, 1, 2)], 0),  # nothing left
        ([NOW - timedelta(weeks=w) for w in (0, 4, 7)], 40),  # too far out to promise
    ],
)
def test_pace_omitted_without_enough_signal(dates: list[datetime], remaining: int) -> None:
    assert estimate_weeks_to_next_level(dates, remaining, NOW) is None


# --- use case -------------------------------------------------------------


def _level(level_id: str, seq: int, name: str) -> SimpleNamespace:
    return SimpleNamespace(level_id=level_id, sequence=seq, name=name)


def _skill(skill_id: str, seq: int, name: str, required: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        skill_id=skill_id, sequence=seq, name=name, is_required=required, level_id="L2"
    )


LEVELS = [
    _level("L1", 1, "Grip & Control"),
    _level("L2", 2, "Net & Movement"),
    _level("L3", 3, "Serve"),
]
SKILLS = {
    "L1": [_skill("grip", 1, "Grip")],
    "L2": [
        _skill("lunge", 1, "Lunge"),
        _skill("split", 2, "Split step"),
        _skill("net", 3, "Backhand net shot"),
        _skill("rally", 4, "Net rally"),
    ],
}


class _Lookup:
    async def get_skill(self, skill_id: str) -> object | None:
        return next((s for ss in SKILLS.values() for s in ss if s.skill_id == skill_id), None)

    async def get_level(self, level_id: str) -> object | None:
        return next((lv for lv in LEVELS if lv.level_id == level_id), None)

    async def list_skills_for_level(self, level_id: str) -> list[object]:
        return list(SKILLS.get(level_id, []))

    async def list_levels_for_program(self, program_id: str) -> list[object]:
        return list(reversed(LEVELS))  # order must not matter

    async def get_next_level(self, program_id: str, current_sequence: int) -> object | None:
        return None


def _progress(
    skill_id: str, status: str, at: datetime, level_id: str = "L2"
) -> StudentSkillProgress:
    return StudentSkillProgress(
        skill_progress_id=f"sp-{skill_id}",
        academy_id="a",
        student_id=STUDENT,
        skill_id=skill_id,
        level_id=level_id,
        program_id=PROGRAM,
        status=status,  # type: ignore[arg-type]
        last_updated_at=at,
        last_updated_by="coach-1",
    )


def _attempt(skill_id: str, at: datetime, notes: str, passed: bool = True) -> TestAttempt:
    return TestAttempt(
        attempt_id=f"ta-{skill_id}-{at.isoformat()}",
        academy_id="a",
        student_id=STUDENT,
        skill_id=skill_id,
        level_id="L2",
        program_id=PROGRAM,
        coach_id="coach-1",
        scoring_type="COACH_APPROVAL",
        attempts_count=1,
        success_count=1 if passed else 0,
        score=100.0 if passed else 0.0,
        passed=passed,
        notes=notes,
        tested_at=at,
    )


class _Repos:
    def __init__(self, *, placed: bool = True) -> None:
        self.rows = [
            # naive datetimes, as Mongo returns them
            _progress("lunge", "PASSED", (NOW - timedelta(days=2)).replace(tzinfo=None)),
            _progress("split", "PASSED", NOW - timedelta(days=9)),
            _progress("net", "PRACTICING", NOW - timedelta(days=1)),
            _progress("grip", "PASSED", NOW - timedelta(days=20), level_id="L1"),
        ]
        self.attempts = {
            "lunge": [
                _attempt("lunge", NOW - timedelta(days=5), "Not yet", passed=False),
                _attempt("lunge", NOW - timedelta(days=2), "  Much quicker to the net.  "),
            ],
            "split": [_attempt("split", NOW - timedelta(days=9), "Marked as mastered in class")],
        }
        self.certs = [
            SkillCertificate(
                cert_id="cert-1",
                academy_id="a",
                student_id=STUDENT,
                program_id=PROGRAM,
                level_id="L1",
                cert_number="BLN-L1-0001",
                student_name="Aarav",
                level_name="Grip & Control",
                program_name="Pathway",
                completed_at=NOW - timedelta(days=14),
                issued_by="system",
                issued_at=NOW - timedelta(days=14),
            )
        ]
        self.placed = placed

    async def get_active(self, student_id: str, program_id: str) -> StudentLevelProgress | None:
        if not self.placed:
            return None
        return StudentLevelProgress(
            progress_id="lp-1",
            academy_id="a",
            student_id=student_id,
            program_id=program_id,
            level_id="L2",
            started_at=NOW - timedelta(days=14),
            created_at=NOW - timedelta(days=14),
        )

    async def list_for_student_level(
        self, student_id: str, level_id: str
    ) -> list[StudentSkillProgress]:
        return [r for r in self.rows if r.level_id == level_id]

    async def list_recent_for_student(
        self, student_id: str, limit: int = 10
    ) -> list[StudentSkillProgress]:
        return sorted(
            self.rows, key=lambda r: r.last_updated_at.replace(tzinfo=None), reverse=True
        )[:limit]

    async def list_for_student_skill(self, student_id: str, skill_id: str) -> list[TestAttempt]:
        return self.attempts.get(skill_id, [])

    async def list_for_student(self, student_id: str) -> list[SkillCertificate]:
        return self.certs


class _LevelRows:
    """Level progress: the active row from ``_Repos`` plus finished rows."""

    def __init__(self, repos: _Repos, completed: list[str]) -> None:
        self._repos = repos
        self._completed = completed

    async def get_active(self, student_id: str, program_id: str) -> StudentLevelProgress | None:
        return await self._repos.get_active(student_id, program_id)

    async def list_for_student(self, student_id: str) -> list[StudentLevelProgress]:
        return [
            StudentLevelProgress(
                progress_id=f"lp-{level_id}",
                academy_id="a",
                student_id=student_id,
                program_id=PROGRAM,
                level_id=level_id,
                status="completed",
                started_at=NOW - timedelta(days=60 - i),
                completed_at=NOW - timedelta(days=30 - i),
                created_at=NOW - timedelta(days=60 - i),
            )
            for i, level_id in enumerate(self._completed)
        ]


def _use_case(repos: _Repos, completed: list[str] | None = None) -> GetParentJourney:
    return GetParentJourney(
        level_progress=_LevelRows(repos, completed or []),  # type: ignore[arg-type]
        skill_progress=repos,  # type: ignore[arg-type]
        skill_lookup=_Lookup(),  # type: ignore[arg-type]
        certificates=repos,  # type: ignore[arg-type]
        test_attempts=repos,  # type: ignore[arg-type]
    )


async def test_journey_shapes_levels_ring_checklist_and_focus() -> None:
    journey = await _use_case(_Repos()).execute(STUDENT, PROGRAM, now=NOW)

    assert [(lv.number, lv.state) for lv in journey.levels] == [
        (1, "done"),
        (2, "current"),
        (3, "upcoming"),
    ]
    current = journey.current_level
    assert current is not None
    assert (current.number, current.name) == (2, "Net & Movement")
    assert (current.skills_done, current.skills_total, current.skills_remaining) == (2, 4, 2)
    assert current.has_next_level is True
    # 3 passes in 20 days (~2.9 weeks) -> ~1.05/week -> 2 left -> 2 weeks
    assert current.pace_weeks == 2
    assert [(s.name, s.state) for s in journey.skills] == [
        ("Lunge", "got_it"),
        ("Split step", "got_it"),
        ("Backhand net shot", "working_on_it"),
        ("Net rally", "coming_up"),
    ]
    assert (journey.focus_skill_id, journey.focus_skill_name) == ("net", "Backhand net shot")


async def test_recent_wins_merge_passes_and_certificates_newest_first() -> None:
    journey = await _use_case(_Repos()).execute(STUDENT, PROGRAM, now=NOW)

    assert [(w.kind, w.title) for w in journey.recent_wins] == [
        ("skill", "Lunge"),
        ("skill", "Split step"),
        ("certificate", "Grip & Control"),
        ("skill", "Grip"),
    ]
    # Test-attempt notes are coach-facing; none reach the parent payload.
    assert "Much quicker" not in journey.model_dump_json()
    assert journey.recent_wins[0].at == NOW - timedelta(days=2)
    assert journey.recent_wins[2].cert_id == "cert-1"


async def test_unplaced_child_still_sees_wins_but_no_level() -> None:
    journey = await _use_case(_Repos(placed=False)).execute(STUDENT, PROGRAM, now=NOW)

    assert journey.current_level is None
    assert journey.levels == []
    assert journey.skills == []
    assert journey.focus_skill_id is None
    assert len(journey.recent_wins) == 4


async def test_finishing_the_last_level_is_not_reported_as_unplaced() -> None:
    journey = await _use_case(_Repos(placed=False), completed=["L1", "L2", "L3"]).execute(
        STUDENT, PROGRAM, now=NOW
    )

    assert journey.pathway_complete is True
    assert journey.current_level is None
    assert [(lv.number, lv.state) for lv in journey.levels] == [
        (1, "done"),
        (2, "done"),
        (3, "done"),
    ]


async def test_completed_earlier_level_without_active_row_is_still_unplaced() -> None:
    # Only the last level's completion means the pathway is finished.
    journey = await _use_case(_Repos(placed=False), completed=["L1"]).execute(
        STUDENT, PROGRAM, now=NOW
    )

    assert journey.pathway_complete is False
    assert journey.levels == []
