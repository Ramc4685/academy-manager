"""The pass date rule shared by the admin passport and the progress summary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from backend.v2.contexts.student_progress.domain.models import skill_passed_at

T1 = datetime(2026, 11, 1, tzinfo=UTC)
T2 = datetime(2026, 11, 10, tzinfo=UTC)
WRITE = datetime(2026, 11, 12, tzinfo=UTC)


@dataclass
class Attempt:
    passed: bool
    tested_at: datetime


def test_not_passed_has_no_date() -> None:
    assert skill_passed_at("PRACTICING", [Attempt(True, T1)], WRITE) is None


def test_latest_passing_attempt_wins_over_failures_and_the_write() -> None:
    attempts = [Attempt(True, T1), Attempt(True, T2), Attempt(False, WRITE)]
    assert skill_passed_at("PASSED", attempts, WRITE) == T2


def test_pass_without_an_attempt_uses_the_progress_write() -> None:
    assert skill_passed_at("PASSED", [Attempt(False, T1)], WRITE) == WRITE
    assert skill_passed_at("PASSED", [], None) is None
