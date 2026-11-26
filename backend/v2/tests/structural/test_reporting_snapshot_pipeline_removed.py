"""The reporting-snapshot pipeline is gone (S38) and must not come back.

Nothing ever wrote the snapshot collections, so every report built on them
read zero. Attendance trends and coach utilisation now read held classes
(``finance.infrastructure.mongo_held_class_reader``). Migration 0104, which
indexed the old collections, stays: migrations are append-only.
"""

from __future__ import annotations

from pathlib import Path

V2_ROOT = Path(__file__).resolve().parents[2]

_REMOVED = (
    "contexts.finance.application.use_cases.compute_reporting_snapshots",
    "contexts.finance.infrastructure.mongo_reporting_snapshot_repos",
    "contexts.finance.infrastructure.mongo_attendance_snapshot_reader",
    "contexts.finance.infrastructure.mongo_coach_payout_snapshot_reader",
    "contexts.finance.domain.reporting_snapshots",
)
_SNAPSHOT_COLLECTIONS = (
    "academy_revenue_snapshots",
    "session_attendance_snapshots",
    "coach_payout_snapshots",
)


def _sources() -> list[Path]:
    return [
        path
        for path in V2_ROOT.rglob("*.py")
        if "migrations" not in path.parts
        and "tests" not in path.parts
        and "__pycache__" not in path.parts
    ]


def test_removed_snapshot_modules_stay_removed() -> None:
    for dotted in _REMOVED:
        assert not (V2_ROOT / (dotted.replace(".", "/") + ".py")).exists(), dotted


def test_nothing_imports_or_reads_the_snapshot_pipeline() -> None:
    offenders = [
        f"{path.relative_to(V2_ROOT)}: {needle}"
        for path in _sources()
        for needle in (*_REMOVED, *_SNAPSHOT_COLLECTIONS)
        if needle.rsplit(".", 1)[-1] in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
