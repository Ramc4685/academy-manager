"""Interface tests for the CSV family import routes (roadmap L8a).

The real admin router with recording stand-ins for the use cases (their
behaviour, tenancy and idempotency are proven on a real ``mongod`` in
``contract/test_crm_family_import_real_mongo.py``). Checks the persona gate
(coach, parent, billing and front desk get the wrong-persona 404), that the
academy is the caller's tenant and never the body's, the body caps, the
response shape and the domain error mapping.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.contexts.crm.application.use_cases.family_import import (
    CommitFamilyImportResult,
    ImportBatch,
    ImportSummary,
    PlannedRow,
)
from backend.v2.contexts.crm.domain.errors import (
    ImportBatchNotFound,
    ImportNotCommittable,
    InvalidImportFile,
)
from backend.v2.contexts.crm.domain.family_import import ImportRow, RowIssue
from backend.v2.interfaces.admin.family_import_routes import (
    MAX_BODY_BYTES,
    get_admin_family_import,
)
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.http.rate_limit import _PATH_LIMIT_OVERRIDES
from backend.v2.shared.tenancy.context import _current as _tenant

A = "acad-a"
PREVIEW = "/api/v2/admin/imports/families/preview"
COMMIT = "/api/v2/admin/imports/families/commit"
NOW = datetime(2026, 9, 24, 15, 0, tzinfo=UTC)


def _batch(status: str = "previewed", *, error: bool = False) -> ImportBatch:
    rows = (
        PlannedRow(
            row=ImportRow(
                line=2,
                parent_name="Pat Testparent",
                student_name="Kit Testkid",
                parent_email="pat@example.test",
                parent_phone="5550102030",
            ),
            family_key="email:pat@example.test",
            new_family_id="parent_new",
            student_id="stu-1",
            status="create",
            family_action="existing",
            family_id="fam/1",
            family_name="Pat Testparent",
            plan_warnings=("Matches the inquiry from Pat.",),
        ),
        PlannedRow(
            row=ImportRow(
                line=3,
                parent_name="Sam",
                student_name="Lee",
                errors=(RowIssue("parent_email", "Give the parent's email or phone."),),
            ),
            family_key=None,
            new_family_id=None,
            student_id=None,
            status="error",
        ),
    )
    return ImportBatch(
        import_batch_id="batch-1",
        kind="families",
        status=status,  # type: ignore[arg-type]
        file_sha256="0" * 64,
        filename="families.csv",
        created_by="u-admin",
        created_at=NOW,
        updated_at=NOW,
        rows=rows if error else rows[:1],
        summary=ImportSummary(
            rows_total=2 if error else 1,
            rows_create=1,
            rows_skip=0,
            rows_error=1 if error else 0,
            families_new=0,
            families_existing=1,
        ),
    )


class _Preview:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.raise_: Exception | None = None

    async def execute(self, academy_id: str, **kwargs: Any) -> ImportBatch:
        self.calls.append((academy_id, kwargs))
        if self.raise_:
            raise self.raise_
        return _batch(error=True)


class _Commit:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.raise_: Exception | None = None

    async def execute(self, academy_id: str, **kwargs: Any) -> CommitFamilyImportResult:
        self.calls.append((academy_id, kwargs))
        if self.raise_:
            raise self.raise_
        return CommitFamilyImportResult(
            _batch("committed"), already_committed=False, students_inserted=1
        )


class Caller:
    def __init__(self) -> None:
        self.be("u-admin", "admin")
        #: What the auth middleware put in the tenant context (None = unset).
        self.tenant: str | None = A

    def be(self, user_id: str, *roles: str) -> None:
        self.claims = AuthClaims(
            user_id=user_id,
            email=f"{user_id}@example.test",
            academy_id=A,
            roles=roles,  # type: ignore[arg-type]
        )


@pytest.fixture
def caller() -> Caller:
    return Caller()


@pytest.fixture
def services() -> SimpleNamespace:
    async def academy_today(academy_id: str) -> date:
        return date(2026, 9, 24)

    return SimpleNamespace(preview=_Preview(), commit=_Commit(), academy_today=academy_today)


@pytest.fixture
def client(caller: Caller, services: SimpleNamespace) -> Iterator[TestClient]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")

    async def claims() -> AuthClaims:
        _tenant.set(caller.tenant)
        return caller.claims

    app.dependency_overrides[get_auth_claims] = claims
    app.dependency_overrides[get_admin_family_import] = lambda: services
    with TestClient(app) as c:
        yield c


def test_preview_answers_the_batch_for_the_tenant(client: TestClient, services: Any) -> None:
    response = client.post(PREVIEW, json={"filename": "families.csv", "csv": "a,b\n"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["import_batch_id"] == "batch-1"
    assert body["can_commit"] is False  # one error row
    assert body["summary"]["rows_error"] == 1
    first, second = body["rows"]
    assert first["status"] == "create"
    assert first["family_link"] == "/admin/families/fam%2F1"
    assert first["warnings"] == ["Matches the inquiry from Pat."]
    assert second["errors"] == [
        {"field": "parent_email", "message": "Give the parent's email or phone."}
    ]
    ((academy, kwargs),) = services.preview.calls
    assert academy == A
    assert kwargs["csv_text"] == "a,b\n"
    assert kwargs["actor_id"] == "u-admin"
    assert kwargs["today"] == date(2026, 9, 24)


def test_commit_answers_the_committed_batch(client: TestClient, services: Any) -> None:
    response = client.post(COMMIT, json={"import_batch_id": "batch-1"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "committed"
    assert body["already_committed"] is False
    assert body["students_inserted"] == 1
    assert body["can_commit"] is False
    assert services.commit.calls == [(A, {"import_batch_id": "batch-1", "actor_id": "u-admin"})]


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (InvalidImportFile("bad"), 422, "Crm.InvalidImportFile"),
        (ImportBatchNotFound("nope"), 404, "Crm.ImportBatchNotFound"),
        (ImportNotCommittable("no", reason="has_errors"), 409, "Crm.ImportNotCommittable"),
    ],
)
def test_domain_errors_map_to_their_status(
    client: TestClient, services: Any, error: Exception, status: int, code: str
) -> None:
    services.preview.raise_ = error
    services.commit.raise_ = error
    path, body = (PREVIEW, {"csv": "x"}) if status == 422 else (COMMIT, {"import_batch_id": "b"})
    response = client.post(path, json=body)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


@pytest.mark.parametrize("roles", [("coach",), ("parent",), ("billing",), ("front_desk",)])
def test_non_admins_get_the_wrong_persona_404(
    client: TestClient, caller: Caller, services: Any, roles: tuple[str, ...]
) -> None:
    caller.be("u-other", *roles)
    assert client.post(PREVIEW, json={"csv": "a"}).status_code == 404
    assert client.post(COMMIT, json={"import_batch_id": "b"}).status_code == 404
    assert services.preview.calls == [] and services.commit.calls == []


def test_owner_with_admin_role_is_admitted(client: TestClient, caller: Caller) -> None:
    caller.be("u-owner", "owner", "admin")
    assert client.post(COMMIT, json={"import_batch_id": "b"}).status_code == 200


def test_the_body_cannot_carry_an_academy(client: TestClient, services: Any) -> None:
    assert client.post(PREVIEW, json={"csv": "a", "academy_id": "acad-b"}).status_code == 422
    assert (
        client.post(COMMIT, json={"import_batch_id": "b", "academy_id": "acad-b"}).status_code
        == 422
    )
    assert services.preview.calls == [] and services.commit.calls == []


def test_malformed_and_oversized_bodies_are_refused_before_parsing(
    client: TestClient, services: Any
) -> None:
    assert client.post(PREVIEW, content=b"not json").status_code == 422
    assert client.post(PREVIEW, json={"filename": "x"}).status_code == 422
    big = b'{"csv": "' + b"a" * MAX_BODY_BYTES + b'"}'
    assert client.post(PREVIEW, content=big).status_code == 413
    assert client.post(COMMIT, json={"import_batch_id": "b" * 65}).status_code == 422
    assert services.preview.calls == []


def test_the_routes_are_rate_limited() -> None:
    assert ("POST", PREVIEW) in _PATH_LIMIT_OVERRIDES
    assert ("POST", COMMIT) in _PATH_LIMIT_OVERRIDES


def test_an_unset_tenant_context_is_refused_not_guessed_from_claims(
    client: TestClient, caller: Caller, services: Any
) -> None:
    # The batch store scopes by the tenant context; planning against the
    # claims' academy instead would split one request across two tenants.
    caller.tenant = None
    assert client.post(PREVIEW, json={"csv": "a"}).status_code == 503
    assert client.post(COMMIT, json={"import_batch_id": "b"}).status_code == 503
    assert services.preview.calls == [] and services.commit.calls == []


def test_a_tenant_context_that_disagrees_with_the_claims_is_a_404(
    client: TestClient, caller: Caller, services: Any
) -> None:
    caller.tenant = "acad-b"
    assert client.post(PREVIEW, json={"csv": "a"}).status_code == 404
    assert client.post(COMMIT, json={"import_batch_id": "b"}).status_code == 404
    assert services.preview.calls == [] and services.commit.calls == []
