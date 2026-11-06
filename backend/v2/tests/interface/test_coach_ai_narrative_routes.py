"""Coach AI narrative routes: persona gate, the assigned-student guard, the
draft and decision flow, and the AI errors passing through as HTTP."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.composition.ai_narratives import AiNarrativesComposition
from backend.v2.contexts.ai.application.use_cases.draft_progress_narrative import (
    DraftProgressNarrative,
)
from backend.v2.contexts.ai.application.use_cases.record_ai_call import RecordAiCall
from backend.v2.contexts.ai.application.use_cases.student_narratives import (
    DraftStudentNarrative,
    ReviewNarratives,
)
from backend.v2.contexts.ai.infrastructure.disabled_llm_port import DisabledLlmPort
from backend.v2.interfaces.coach.deps import get_coach_use_cases
from backend.v2.interfaces.coach.router import router as coach_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.tests.fixtures.ai_counters import counters_at
from backend.v2.tests.unit.test_progress_narrative import (
    INPUT,
    FakeCalls,
    FakeCap,
    FakeEntitlement,
    FakeFacts,
    FakeLlm,
    FakeNarratives,
    FakeReview,
)

ACADEMY = "test-academy"
COACH, OTHER_COACH, ADMIN, PARENT = "coach-1", "coach-2", "admin-1", "parent-1"
STUDENT, OUTSIDE = "s-aarav", "s-outside"
NOW = datetime(2026, 11, 4, 18, 0, tzinfo=UTC)


def _claims(user_id: str, *roles: str) -> AuthClaims:
    return AuthClaims(
        user_id=user_id, email=f"{user_id}@example.test", academy_id=ACADEMY, roles=tuple(roles)
    )


def _coach_use_cases() -> Any:
    """Only what ``_require_assigned_to_student`` reads: coach-1 covers s1,
    where s-aarav is enrolled; s-outside is enrolled on s2 (coach-2's)."""

    async def enrollments(student_id: str) -> list[Any]:
        return {
            STUDENT: [SimpleNamespace(session_id="s1")],
            OUTSIDE: [SimpleNamespace(session_id="s2")],
        }.get(student_id, [])

    async def is_coach_assigned(coach_id: str, session_id: str) -> bool:
        return (coach_id, session_id) in {(COACH, "s1"), (OTHER_COACH, "s2")}

    async def timezone(_academy_id: str) -> str | None:
        return "America/Chicago"

    return SimpleNamespace(
        get_active_session_enrollments_for_student=enrollments,
        assigned_sessions=SimpleNamespace(is_coach_assigned=is_coach_assigned),
        get_academy_timezone=timezone,
    )


def _narratives(*, llm: Any, entitled: bool = True, review: bool = True, used: int = 0):
    calls, repo = FakeCalls(used=used), FakeNarratives()
    drafter = DraftProgressNarrative(
        llm=llm,
        record_ai_call=RecordAiCall(
            calls=calls,
            counters=counters_at(used, NOW),
            cap_source=FakeCap(),
            clock=lambda: NOW,
        ),
        entitlement=FakeEntitlement(entitled),
    )
    composition = AiNarrativesComposition(
        draft_for_student=DraftStudentNarrative(
            facts=FakeFacts(INPUT),
            drafter=drafter,
            review=FakeReview(review),
            narratives=repo,
            calls=calls,
            clock=lambda: NOW,
        ),
        review=ReviewNarratives(narratives=repo, calls=calls, clock=lambda: NOW),
    )
    return composition, calls, repo


def _client(claims: AuthClaims, narratives: Any | None) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(coach_router, prefix="/api/v2")
    if narratives is not None:
        app.state.ai_narratives = narratives
    use_cases = _coach_use_cases()
    app.dependency_overrides[get_auth_claims] = lambda: claims
    app.dependency_overrides[get_coach_use_cases] = lambda: use_cases
    return TestClient(app)


DRAFT = f"/api/v2/coach/students/{STUDENT}/narrative-draft"


def test_coach_drafts_then_approves_with_edits_and_both_rows_carry_the_coach() -> None:
    composition, calls, _ = _narratives(llm=FakeLlm())
    client = _client(_claims(COACH, "coach"), composition)

    drafted = client.post(DRAFT, json={"date": "2026-11-04"})
    assert drafted.status_code == 201, drafted.text
    row = drafted.json()
    assert (row["status"], row["for_date"], row["kind"], row["approver"]) == (
        "pending_review",
        "2026-11-04",
        "evening_wins",
        None,
    )
    assert row["text"].startswith("Aarav mastered Forecourt movement")

    pending = client.get("/api/v2/coach/narratives/pending?date=2026-11-04")
    assert [n["narrative_id"] for n in pending.json()["narratives"]] == [row["narrative_id"]]

    decided = client.put(
        f"/api/v2/coach/narratives/{row['narrative_id']}/decision",
        json={"status": "approved", "text": "Aarav moved so well today."},
    )
    assert decided.status_code == 200, decided.text
    assert (decided.json()["status"], decided.json()["approver"], decided.json()["text"]) == (
        "approved",
        COACH,
        "Aarav moved so well today.",
    )
    assert calls.approvers == [(calls.recorded[0].call_id, COACH)]
    assert client.get("/api/v2/coach/narratives/pending?date=2026-11-04").json() == {
        "narratives": []
    }
    # A second decision on the same row is a conflict, not a silent success.
    again = client.put(
        f"/api/v2/coach/narratives/{row['narrative_id']}/decision", json={"status": "rejected"}
    )
    assert again.status_code == 409


def test_the_day_s_row_is_readable_by_student_so_a_refresh_keeps_the_draft() -> None:
    composition, _, _ = _narratives(llm=FakeLlm())
    client = _client(_claims(COACH, "coach"), composition)
    url = f"/api/v2/coach/students/{STUDENT}/narrative?date=2026-11-04"
    assert client.get(url).status_code == 404
    drafted = client.post(DRAFT, json={"date": "2026-11-04"}).json()
    assert client.get(url).json() == drafted
    assert client.get(url.replace("2026-11-04", "2026-11-03")).status_code == 404
    client.put(
        f"/api/v2/coach/narratives/{drafted['narrative_id']}/decision", json={"status": "rejected"}
    )
    assert client.get(url).json()["status"] == "rejected"
    # Other personas and a coach off the student's sessions (another academy's
    # coach included) get 404, never the row.
    for claims in (_claims(PARENT, "parent"), _claims(OTHER_COACH, "coach")):
        assert _client(claims, composition).get(url).status_code == 404


def test_review_off_returns_an_approved_row_the_coach_never_sees_as_pending() -> None:
    composition, calls, _ = _narratives(llm=FakeLlm(), review=False)
    client = _client(_claims(COACH, "coach"), composition)
    row = client.post(DRAFT, json={}).json()
    assert (row["status"], row["approver"]) == ("approved", "coach_review_off")
    assert calls.approvers == [(calls.recorded[0].call_id, "coach_review_off")]


def test_an_assistant_only_coach_cannot_draft_or_approve_for_parents() -> None:
    composition, _, _ = _narratives(llm=FakeLlm())
    row = _client(_claims(COACH, "coach"), composition).post(DRAFT, json={}).json()
    assistant = _client(_claims(COACH, "assistant_coach"), composition)
    assert assistant.post(DRAFT, json={}).status_code == 403
    decision = f"/api/v2/coach/narratives/{row['narrative_id']}/decision"
    assert assistant.put(decision, json={"status": "approved"}).status_code == 403
    assert assistant.put(decision, json={"status": "rejected"}).status_code == 200


def test_another_coach_s_pending_rows_are_not_listed_but_a_supervisor_sees_all() -> None:
    composition, _, _ = _narratives(llm=FakeLlm())
    _client(_claims(COACH, "coach"), composition).post(DRAFT, json={"date": "2026-11-04"})
    other = _client(_claims(OTHER_COACH, "coach"), composition)
    assert other.get("/api/v2/coach/narratives/pending?date=2026-11-04").json() == {
        "narratives": []
    }
    admin = _client(_claims(ADMIN, "admin"), composition)
    assert (
        len(admin.get("/api/v2/coach/narratives/pending?date=2026-11-04").json()["narratives"]) == 1
    )


@pytest.mark.parametrize(
    ("claims", "student", "expected"),
    [
        (_claims(PARENT, "parent"), STUDENT, 404),  # wrong persona
        (_claims(ADMIN, "admin"), STUDENT, 404),  # supervisor, not assigned (skill-board guard)
        (_claims(COACH, "coach"), OUTSIDE, 404),  # on another coach's session
        (_claims(COACH, "coach"), "s-unknown", 404),
    ],
)
def test_draft_is_404_off_the_coach_s_sessions_and_for_other_personas(
    claims: AuthClaims, student: str, expected: int
) -> None:
    composition, calls, _ = _narratives(llm=FakeLlm())
    client = _client(claims, composition)
    assert (
        client.post(f"/api/v2/coach/students/{student}/narrative-draft", json={}).status_code
        == expected
    )
    assert calls.recorded == []


def test_decision_on_a_student_outside_the_coach_s_sessions_is_404() -> None:
    composition, _, repo = _narratives(llm=FakeLlm())
    row = _client(_claims(COACH, "coach"), composition).post(DRAFT, json={}).json()
    other = _client(_claims(OTHER_COACH, "coach"), composition)
    resp = other.put(
        f"/api/v2/coach/narratives/{row['narrative_id']}/decision", json={"status": "approved"}
    )
    assert resp.status_code == 404
    assert repo.rows[row["narrative_id"]].status == "pending_review"
    assert (
        other.put("/api/v2/coach/narratives/nope/decision", json={"status": "approved"}).status_code
        == 404
    )


@pytest.mark.parametrize(
    ("kwargs", "status", "code"),
    [
        ({"llm": DisabledLlmPort()}, 503, "Ai.Disabled"),
        ({"llm": FakeLlm(), "entitled": False}, 403, "Ai.NotEntitled"),
        ({"llm": FakeLlm(), "used": 2}, 429, "Ai.MonthlyCapReached"),
        ({"llm": FakeLlm("not json")}, 502, "Ai.ProviderError"),
    ],
)
def test_ai_errors_pass_through_with_their_codes(kwargs: dict, status: int, code: str) -> None:
    composition, _, repo = _narratives(**kwargs)
    resp = _client(_claims(COACH, "coach"), composition).post(DRAFT, json={})
    assert (resp.status_code, resp.json()["error"]["code"]) == (status, code)
    assert repo.rows == {}


def test_unconfigured_state_is_503_and_unknown_body_keys_are_422() -> None:
    assert _client(_claims(COACH, "coach"), None).post(DRAFT, json={}).status_code == 503
    composition, _, _ = _narratives(llm=FakeLlm())
    client = _client(_claims(COACH, "coach"), composition)
    assert client.post(DRAFT, json={"student_name": "x"}).status_code == 422


def test_omitted_date_is_the_academy_s_day_not_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    """02:00 UTC on the 5th is still the evening of the 4th in Chicago, so a
    no-date draft and the pending list both land on 2026-11-04."""
    from backend.v2.interfaces.coach import today_routes

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return datetime(2026, 11, 5, 2, 0, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(today_routes, "datetime", _Clock)
    composition, _, _ = _narratives(llm=FakeLlm())
    client = _client(_claims(COACH, "coach"), composition)
    assert client.post(DRAFT, json={}).json()["for_date"] == "2026-11-04"
    pending = client.get("/api/v2/coach/narratives/pending").json()["narratives"]
    assert [r["for_date"] for r in pending] == ["2026-11-04"]
