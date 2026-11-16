"""Pure milestone rules and the share-page name rule (L5B PR2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from backend.v2.contexts.student_progress.domain.milestones import (
    MilestoneThreshold,
    ProgressSettings,
    reached_milestones,
    share_recipient_name,
)

T0 = datetime(2026, 11, 1, tzinfo=UTC)


def _settings(*thresholds: tuple[str, int, datetime], enabled: bool = True) -> ProgressSettings:
    return ProgressSettings(
        milestones_enabled=enabled,
        milestones=[MilestoneThreshold(kind=k, count=c, since=s) for k, c, s in thresholds],  # type: ignore[arg-type]
    )


def test_defaults_are_off_and_empty() -> None:
    settings = ProgressSettings()
    assert settings.milestones_enabled is False and settings.milestones == []
    assert settings.share_name == "first_name"


def test_reached_at_is_the_nth_pass_regardless_of_input_order() -> None:
    times = [T0 + timedelta(days=d) for d in (5, 1, 3, 2)]
    (hit,) = reached_milestones(
        _settings(("skills_passed", 3, T0)), student_id="s", passed_at=times, completed_at=[]
    )
    assert (hit.milestone_key, hit.reached_at) == ("skills_passed:3", T0 + timedelta(days=3))


def test_threshold_only_counts_milestones_reached_after_it_was_added() -> None:
    times = [T0, T0 + timedelta(days=1)]
    since = T0 + timedelta(hours=12)
    assert (
        reached_milestones(
            _settings(("skills_passed", 1, since)), student_id="s", passed_at=times, completed_at=[]
        )
        == []
    )
    assert [
        m.count
        for m in reached_milestones(
            _settings(("skills_passed", 2, since)), student_id="s", passed_at=times, completed_at=[]
        )
    ] == [2]


def test_off_or_short_reaches_nothing_and_naive_mongo_times_compare() -> None:
    naive = [datetime(2026, 11, 2), datetime(2026, 11, 3)]  # as Mongo returns them
    assert (
        reached_milestones(
            _settings(("levels_completed", 1, T0), enabled=False),
            student_id="s",
            passed_at=[],
            completed_at=naive,
        )
        == []
    )
    assert (
        reached_milestones(
            _settings(("levels_completed", 3, T0)), student_id="s", passed_at=[], completed_at=naive
        )
        == []
    )
    (hit,) = reached_milestones(
        _settings(("levels_completed", 2, T0)), student_id="s", passed_at=[], completed_at=naive
    )
    assert hit.reached_at == datetime(2026, 11, 3, tzinfo=UTC)


def test_duplicate_thresholds_are_refused() -> None:
    with pytest.raises(ValidationError):
        _settings(("skills_passed", 5, T0), ("skills_passed", 5, T0))


@pytest.mark.parametrize(
    ("name", "rule", "shown"),
    [
        ("Maya Patel", "first_name", "Maya"),
        ("Maya Patel", "initial", "M."),
        ("  ", "first_name", "A player"),
    ],
)
def test_share_recipient_name(name: str, rule: str, shown: str) -> None:
    assert share_recipient_name(name, rule) == shown  # type: ignore[arg-type]
