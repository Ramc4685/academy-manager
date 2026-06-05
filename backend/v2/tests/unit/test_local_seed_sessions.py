"""Unit tests for local BLNO seed session shape."""

from __future__ import annotations

import importlib.util
from datetime import UTC, date, datetime
from pathlib import Path
from types import ModuleType


def _load_seed_module() -> ModuleType:
    script_path = Path(__file__).resolve().parents[3] / "scripts" / "seed_local.py"
    spec = importlib.util.spec_from_file_location("seed_local_for_test", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _thursday_template() -> dict[str, object]:
    return {
        "name": "Thursday 6:00 PM - 6:45 PM Beginner",
        "location": "Court",
        "max_students": 15,
        "monthly_price": 100,
        "coach_key": "Gowtham",
        "days_of_week": ["Thu"],
        "start_time": "18:00",
        "end_time": "18:45",
        "start_date": "2026-04-01",
        "end_date": "2026-12-31",
        "skill_level": "Beginner",
        "age_group": "6-12",
    }


def test_seed_session_doc_keeps_recurring_template_fields() -> None:
    module = _load_seed_module()
    created_at = datetime(2026, 6, 4, 15, 0, tzinfo=UTC)

    doc = module.build_recurring_session_doc(
        _thursday_template(),
        session_id="session-thu-6",
        coach_id="coach-gowtham",
        amount_cents=10000,
        created_at=created_at,
    )

    assert doc["session_id"] == "session-thu-6"
    assert doc["coach_id"] == "coach-gowtham"
    assert doc["title"] == "Thursday 6:00 PM - 6:45 PM Beginner"
    assert doc["days_of_week"] == ["Thu"]
    assert doc["start_time"] == "18:00"
    assert doc["end_time"] == "18:45"
    assert doc["timezone"] == "America/Chicago"
    assert doc["start_date"] == "2026-04-01"
    assert doc["end_date"] == "2026-12-31"
    assert doc["status"] == "scheduled"
    assert doc["start_at"] == datetime(2026, 4, 2, 23, 0, tzinfo=UTC)
    assert doc["end_at"] == datetime(2026, 4, 2, 23, 45, tzinfo=UTC)


def test_seed_occurrence_docs_cover_the_maintained_future_window() -> None:
    module = _load_seed_module()
    session_doc = module.build_recurring_session_doc(
        _thursday_template(),
        session_id="session-thu-6",
        coach_id="coach-gowtham",
        amount_cents=10000,
        created_at=datetime(2026, 6, 4, 15, 0, tzinfo=UTC),
    )

    occurrences = module.build_session_occurrence_docs(
        session_doc,
        window_start=date(2026, 6, 4),
        days_forward=60,
    )

    by_date = {
        occ["start_at"].astimezone(module.ZoneInfo("America/Chicago")).date(): occ
        for occ in occurrences
    }
    assert {date(2026, 6, 4), date(2026, 6, 11), date(2026, 6, 18)} <= set(by_date)
    assert max(by_date) == date(2026, 7, 30)
    assert by_date[date(2026, 6, 18)] == {
        "occurrence_id": "session-thu-6:2026-06-18:18:00",
        "academy_id": "blno",
        "session_id": "session-thu-6",
        "template_session_id": "session-thu-6",
        "start_at": datetime(2026, 6, 18, 23, 0, tzinfo=UTC),
        "end_at": datetime(2026, 6, 18, 23, 45, tzinfo=UTC),
        "status": "scheduled",
        "scheduled_coach_id": "coach-gowtham",
        "is_billable": True,
        "is_payable": True,
    }


def test_seed_past_completion_skips_recurring_templates() -> None:
    module = _load_seed_module()
    recurring = module.build_recurring_session_doc(
        _thursday_template(),
        session_id="session-thu-6",
        coach_id="coach-gowtham",
        amount_cents=10000,
        created_at=datetime(2026, 6, 4, 15, 0, tzinfo=UTC),
    )
    dated = {
        "academy_id": "blno",
        "session_id": "special-1",
        "start_at": datetime(2026, 5, 1, 18, 0, tzinfo=UTC),
    }

    assert module.is_concrete_session_for_completion(dated)
    assert not module.is_concrete_session_for_completion(recurring)
