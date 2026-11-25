"""Interface tests for parent absence-notice routes (R1)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.enrollment.application.use_cases.absence_notices import (
    AbsenceNotice,
    DuplicateAbsenceNotice,
    SubmitAbsenceNoticeCommand,
)
from backend.v2.interfaces.parent.deps import get_parent_use_cases
from backend.v2.interfaces.parent.router import router as parent_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers


def _claims(role: str = "parent") -> AuthClaims:
    return AuthClaims(
        user_id="parent-1",
        email=f"{role}@example.com",
        academy_id="acad",
        roles=(role,),  # type: ignore[arg-type]
    )


def _notice(
    *,
    notice_id: str = "notice-1",
    student_id: str = "student-1",
    occurrence_id: str = "occ-1",
    window_met: bool = True,
) -> AbsenceNotice:
    return AbsenceNotice(
        notice_id=notice_id,
        academy_id="acad",
        student_id=student_id,
        occurrence_id=occurrence_id,
        session_id="session-1",
        submitted_by="parent-1",
        submitted_at=datetime(2026, 7, 10, 8, 0, tzinfo=UTC),
        notice_window_met=window_met,
    )


class _ParentUseCases:
    def __init__(
        self,
        *,
        submit_result: AbsenceNotice | None = None,
        submit_error: Exception | None = None,
        list_result: list[AbsenceNotice] | None = None,
    ) -> None:
        self._submit_result = submit_result or _notice()
        self._submit_error = submit_error
        self._list_result = list_result if list_result is not None else [_notice()]
        self.submitted_commands: list[SubmitAbsenceNoticeCommand] = []

    class _Submit:
        def __init__(self, outer: _ParentUseCases) -> None:
            self._outer = outer

        async def execute(self, cmd: SubmitAbsenceNoticeCommand) -> AbsenceNotice:
            self._outer.submitted_commands.append(cmd)
            if self._outer._submit_error is not None:
                raise self._outer._submit_error
            return self._outer._submit_result

    class _List:
        def __init__(self, outer: _ParentUseCases) -> None:
            self._outer = outer

        async def execute(self, parent_id: str) -> list[AbsenceNotice]:
            return self._outer._list_result

    @property
    def submit_absence_notice(self):
        return self._Submit(self)

    @property
    def list_parent_absences(self):
        return self._List(self)


@contextmanager
def _make_client(
    role: str = "parent",
    use_cases: _ParentUseCases | None = None,
) -> Iterator[TestClient]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(parent_router, prefix="/api/v2")
    app.dependency_overrides[get_auth_claims] = lambda: _claims(role)
    app.dependency_overrides[get_parent_use_cases] = lambda: use_cases or _ParentUseCases()
    with TestClient(app) as client:
        yield client


def test_post_absence_notice_returns_201_with_window_met() -> None:
    use_cases = _ParentUseCases(submit_result=_notice(window_met=True))
    with _make_client(use_cases=use_cases) as client:
        response = client.post(
            "/api/v2/parent/absences",
            json={"student_id": "student-1", "occurrence_id": "occ-1"},
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["notice_id"] == "notice-1"
    assert body["student_id"] == "student-1"
    assert body["occurrence_id"] == "occ-1"
    assert body["notice_window_met"] is True
    [cmd] = use_cases.submitted_commands
    assert cmd.parent_id == "parent-1"
    assert cmd.student_id == "student-1"
    assert cmd.occurrence_id == "occ-1"


def test_get_absences_lists_parent_notices() -> None:
    use_cases = _ParentUseCases(
        list_result=[_notice(notice_id="notice-1"), _notice(notice_id="notice-2")]
    )
    with _make_client(use_cases=use_cases) as client:
        response = client.get("/api/v2/parent/absences")

    assert response.status_code == 200, response.text
    body = response.json()
    assert [n["notice_id"] for n in body["notices"]] == ["notice-1", "notice-2"]


def test_wrong_persona_cannot_submit_absence_notice() -> None:
    with _make_client("admin") as client:
        response = client.post(
            "/api/v2/parent/absences",
            json={"student_id": "student-1", "occurrence_id": "occ-1"},
        )

    assert response.status_code == 404


def test_wrong_persona_cannot_list_absences() -> None:
    with _make_client("coach") as client:
        response = client.get("/api/v2/parent/absences")

    assert response.status_code == 404


def test_duplicate_absence_notice_returns_409_with_error_code() -> None:
    use_cases = _ParentUseCases(
        submit_error=DuplicateAbsenceNotice("already submitted", occurrence_id="occ-1")
    )
    with _make_client(use_cases=use_cases) as client:
        response = client.post(
            "/api/v2/parent/absences",
            json={"student_id": "student-1", "occurrence_id": "occ-1"},
        )

    assert response.status_code == 409, response.text
    body = response.json()
    assert body["error"]["code"] == "Enrollment.DuplicateAbsenceNotice"


def test_get_absences_names_the_missed_class_per_occurrence() -> None:
    # Two notices for one child on different Saturdays are not duplicates; the
    # card has to show which class each one is for.
    use_cases = _ParentUseCases(
        list_result=[
            _notice(notice_id="n-1", occurrence_id="sat:2026-11-28:09:00"),
            _notice(notice_id="n-2", occurrence_id="sat:2026-12-05:09:00"),
        ]
    )
    asked: list[list[str]] = []

    async def _resolver(occurrence_ids: list[str]) -> dict[str, dict[str, object]]:
        asked.append(occurrence_ids)
        return {
            oid: {
                "occurrence_id": oid,
                "session_id": "sat",
                "session_title": "Junior Beginners",
                "start_at": f"{oid.split(':')[1]}T15:00:00Z",
                "end_at": f"{oid.split(':')[1]}T16:00:00Z",
                "timezone": "America/Chicago",
                "status": "scheduled",
            }
            for oid in occurrence_ids
            if oid != "sat:2026-12-05:09:00"
        }

    use_cases.resolve_assigned_classes = _resolver  # type: ignore[attr-defined]
    with _make_client(use_cases=use_cases) as client:
        response = client.get("/api/v2/parent/absences")

    assert response.status_code == 200, response.text
    rows = {n["notice_id"]: n for n in response.json()["notices"]}
    assert asked == [["sat:2026-11-28:09:00", "sat:2026-12-05:09:00"]]
    assert rows["n-1"]["missed_class"]["session_title"] == "Junior Beginners"
    assert rows["n-1"]["missed_class"]["start_at"].startswith("2026-11-28T15:00:00")
    # Unresolvable occurrence degrades to no details, not a 500.
    assert rows["n-2"]["missed_class"] is None


def test_get_absences_carries_each_notices_makeup_state_and_booked_class() -> None:
    from backend.v2.contexts.enrollment.application.use_cases.makeup_requests import (
        AbsenceMakeupStatus,
    )

    use_cases = _ParentUseCases(
        list_result=[
            _notice(notice_id="n-1", occurrence_id="occ-1"),
            _notice(notice_id="n-2", occurrence_id="occ-2"),
        ]
    )
    asked: list[list[tuple[str, str]]] = []

    class _Describe:
        async def execute(self, keys):
            asked.append(keys)
            return {
                ("student-1", "occ-1"): AbsenceMakeupStatus(
                    state="booked", booked_occurrence_id="occ-target"
                ),
                ("student-1", "occ-2"): AbsenceMakeupStatus(
                    state="eligible", expires_at=datetime(2026, 12, 1, tzinfo=UTC)
                ),
            }

    async def _resolver(occurrence_ids: list[str]) -> dict[str, dict[str, object]]:
        return {
            oid: {
                "occurrence_id": oid,
                "session_id": "s",
                "session_title": "Saturday Makeup",
                "start_at": "2026-12-05T15:00:00Z",
                "end_at": "2026-12-05T16:00:00Z",
                "status": "scheduled",
            }
            for oid in occurrence_ids
        }

    use_cases.describe_absence_makeups = _Describe()  # type: ignore[attr-defined]
    use_cases.resolve_assigned_classes = _resolver  # type: ignore[attr-defined]
    with _make_client(use_cases=use_cases) as client:
        response = client.get("/api/v2/parent/absences")

    assert response.status_code == 200, response.text
    rows = {n["notice_id"]: n for n in response.json()["notices"]}
    assert asked == [[("student-1", "occ-1"), ("student-1", "occ-2")]]
    assert rows["n-1"]["makeup"]["state"] == "booked"
    assert rows["n-1"]["makeup"]["booked_class"]["session_title"] == "Saturday Makeup"
    assert rows["n-2"]["makeup"]["state"] == "eligible"
    assert rows["n-2"]["makeup"]["booked_class"] is None


def test_get_absences_without_the_describer_still_lists_notices() -> None:
    with _make_client() as client:
        response = client.get("/api/v2/parent/absences")

    assert response.status_code == 200, response.text
    assert response.json()["notices"][0]["makeup"] is None
