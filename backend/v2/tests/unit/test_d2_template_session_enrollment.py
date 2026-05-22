from __future__ import annotations

import datetime

from backend.v2.contexts.coaching.application.ports import OccurrenceDetails


def test_occurrence_details_has_template_session_id():
    od = OccurrenceDetails(
        occurrence_id="occ-jun4",
        session_id="sess-jun4",
        starts_at=datetime.datetime(2026, 6, 4, 18, 0, tzinfo=datetime.timezone.utc),
        status="scheduled",
        scheduled_coach_id="coach1",
        template_session_id="sess-may28",
    )
    assert od.template_session_id == "sess-may28"


def test_occurrence_details_template_session_id_optional():
    od = OccurrenceDetails(
        occurrence_id="occ1",
        session_id="sess1",
        starts_at=datetime.datetime(2026, 6, 4, 18, 0, tzinfo=datetime.timezone.utc),
        status="scheduled",
        scheduled_coach_id="coach1",
    )
    assert od.template_session_id is None
