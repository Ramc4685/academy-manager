"""S10: one rule for an unpriced class."""

from backend.v2.contexts.enrollment.application.pricing_state import is_unpriced
from backend.v2.interfaces.admin.views import AdminSessionView


def test_none_is_unpriced_and_zero_is_free():
    assert is_unpriced(None)
    assert not is_unpriced(0)
    assert not is_unpriced(9000)


def test_admin_session_view_carries_the_flag():
    base = {
        "session_id": "s1",
        "coach_id": "c1",
        "title": "Tuesday Intermediate",
        "location": "Court 1",
        "start_at": "2026-11-24T18:00:00Z",
        "end_at": "2026-11-24T19:00:00Z",
        "capacity": 10,
        "status": "scheduled",
    }
    assert AdminSessionView(**base).model_dump()["unpriced"] is True
    assert AdminSessionView(**base, amount_cents=0).model_dump()["unpriced"] is False
