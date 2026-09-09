"""GET /api/v2/parent/home — the one read that backs the kid-first Home."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.interfaces.parent.deps import get_parent_use_cases
from backend.v2.interfaces.parent.router import router as parent_router
from backend.v2.interfaces.parent.views import ParentHomeResponse
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers


def _claims(role: str = "parent", user_id: str = "parent-1") -> AuthClaims:
    return AuthClaims(
        user_id=user_id,
        email=f"{role}@example.com",
        academy_id="acad",
        roles=(role,),  # type: ignore[arg-type]
    )


class _HomeUseCases:
    """Duck-typed stand-in exposing only what the route touches."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    async def get_parent_home(self, *, parent_id: str) -> dict[str, Any]:
        self.calls.append({"parent_id": parent_id})
        return self.payload


def _two_child_payload() -> dict[str, Any]:
    return {
        "children": [
            {
                "student_id": "st-1",
                "full_name": "Asha Rao",
                "next_session": {
                    "occurrence_id": "occ-1",
                    "session_id": "sess-1",
                    "session_title": "Junior Badminton",
                    "location": "Court 2",
                    "start_at": datetime(2026, 9, 8, 23, 0, tzinfo=UTC),
                    "end_at": datetime(2026, 9, 9, 0, 0, tzinfo=UTC),
                    "coach_name": None,
                },
                "attendance_this_month": {"present": 6, "total": 7},
                "latest_milestone": {
                    "kind": "skill",
                    "label": "Backhand Lift",
                    "at": datetime(2026, 9, 4, 15, 30, tzinfo=UTC),
                },
            },
            {
                "student_id": "st-2",
                "full_name": "Dev Rao",
                "next_session": None,
                "attendance_this_month": {"present": 0, "total": 0},
                "latest_milestone": {
                    "kind": "note",
                    "label": "Great focus in drills today",
                    "at": datetime(2026, 9, 2, 1, 15, tzinfo=UTC),
                },
            },
        ],
        "balance": {
            "amount_due_cents": 12_000,
            "currency": "usd",
            "due_date": date(2026, 9, 12),
            "open_invoice_count": 2,
            "payment_failed": False,
        },
        "month_label": "September",
        "timezone": "America/Chicago",
    }


def _empty_payload() -> dict[str, Any]:
    return {
        "children": [],
        "balance": {
            "amount_due_cents": 0,
            "currency": "usd",
            "due_date": None,
            "open_invoice_count": 0,
            "payment_failed": False,
        },
        "month_label": "September",
        "timezone": "UTC",
    }


@contextmanager
def _make_client(
    payload: dict[str, Any] | None = None,
    role: str = "parent",
    user_id: str = "parent-1",
) -> Iterator[tuple[TestClient, _HomeUseCases]]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(parent_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: _claims(role, user_id)
    use_cases = _HomeUseCases(payload if payload is not None else _two_child_payload())
    app.dependency_overrides[get_parent_use_cases] = lambda: use_cases
    with TestClient(app) as client:
        yield client, use_cases


def test_home_returns_one_card_per_child_in_order() -> None:
    with _make_client() as (client, use_cases):
        response = client.get("/api/v2/parent/home")

    assert response.status_code == 200
    body = response.json()
    assert use_cases.calls == [{"parent_id": "parent-1"}]
    assert [child["student_id"] for child in body["children"]] == ["st-1", "st-2"]
    assert body["children"][0]["full_name"] == "Asha Rao"
    assert body["children"][0]["attendance_this_month"] == {"present": 6, "total": 7}
    assert body["children"][0]["latest_milestone"]["kind"] == "skill"
    assert body["children"][0]["next_session"]["location"] == "Court 2"
    # coach_name is carried for shape parity and is always null today.
    assert body["children"][0]["next_session"]["coach_name"] is None
    assert body["month_label"] == "September"
    assert body["timezone"] == "America/Chicago"
    assert body["balance"] == {
        "amount_due_cents": 12_000,
        "currency": "usd",
        "due_date": "2026-09-12",
        "open_invoice_count": 2,
        "payment_failed": False,
    }
    # The contract shape is the response model, not just whatever dict we built.
    ParentHomeResponse.model_validate(body)


def test_home_child_without_upcoming_session_has_null_next_session() -> None:
    with _make_client() as (client, _use_cases):
        body = client.get("/api/v2/parent/home").json()

    second = body["children"][1]
    assert second["next_session"] is None
    assert second["attendance_this_month"] == {"present": 0, "total": 0}
    assert second["latest_milestone"] == {
        "kind": "note",
        "label": "Great focus in drills today",
        "at": "2026-09-02T01:15:00Z",
    }


def test_home_with_no_children_is_200_with_empty_list_and_zeroed_balance() -> None:
    with _make_client(_empty_payload()) as (client, _use_cases):
        response = client.get("/api/v2/parent/home")

    assert response.status_code == 200
    body = response.json()
    assert body["children"] == []
    assert body["balance"]["amount_due_cents"] == 0
    assert body["balance"]["open_invoice_count"] == 0
    assert body["balance"]["payment_failed"] is False
    assert body["balance"]["due_date"] is None
    ParentHomeResponse.model_validate(body)


def test_home_hides_route_existence_from_a_non_parent_persona() -> None:
    # require_persona raises 404, never 403 — route existence is not leaked.
    with _make_client(role="coach") as (client, use_cases):
        response = client.get("/api/v2/parent/home")

    assert response.status_code == 404
    assert use_cases.calls == []


def test_home_requires_authentication() -> None:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(parent_router, prefix="/api/v2")
    app.dependency_overrides[get_parent_use_cases] = lambda: _HomeUseCases(_two_child_payload())
    with TestClient(app) as client:
        assert client.get("/api/v2/parent/home").status_code == 401
