from __future__ import annotations

from pathlib import Path


def test_admin_session_roster_query_excludes_paused_enrollments() -> None:
    source = (Path(__file__).parent.parent.parent / "composition" / "admin.py").read_text()

    assert '"status": {"$in": ["active", "paused"]}' not in source
