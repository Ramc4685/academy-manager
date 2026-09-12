"""``DELETE /admin/enrollments/{id}`` honours ``delete_enrollment_requires_owner`` (#741).

The Settings toggle shipped in #701 and PR #700 deferred the backend half to
#697, which never landed: the route stayed ``require_persona("admin")`` and
never read the policy, so the Settings control claimed an authorization
boundary that did not exist.

Modelled on ``test_admin_withdrawal_credit.py`` — same action-level gate
shape, same 404-not-403 answer a plain admin gets from ``require_owner``.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.v2.contexts.enrollment.application.use_cases.departure_policies import (
    GetEnrollmentDeparturePolicy,
)
from backend.v2.contexts.enrollment.domain.departure_policy import EnrollmentDeparturePolicy
from backend.v2.tests.fixtures.enrollment_fakes import FakeDeparturePolicyRepo
from backend.v2.tests.interface.conftest import (  # type: ignore[attr-defined]
    _build_admin_use_cases,
    _claims,
    _make_admin_app,
)


def _client(admin_seed: Any, role: str, *, requires_owner: bool | None) -> Iterator[TestClient]:
    """An admin app whose departure policy sets ``delete_enrollment_requires_owner``.

    ``requires_owner=None`` leaves ``AdminUseCases.departure_policy`` unset —
    the fixture shape every other interface test runs with, and the shape a
    tenant whose policy was never composed has in production.
    """
    use_cases = _build_admin_use_cases(admin_seed)
    if requires_owner is not None:
        policy = EnrollmentDeparturePolicy.default("acad").model_copy(
            update={"delete_enrollment_requires_owner": requires_owner}
        )
        use_cases = dataclasses.replace(
            use_cases,
            departure_policy=GetEnrollmentDeparturePolicy(FakeDeparturePolicyRepo(policy)),
        )
    app = _make_admin_app(_claims(role), use_cases)
    with TestClient(app) as client:
        client.seed = admin_seed  # type: ignore[attr-defined]
        yield client


@pytest.fixture
def owner_delete_required_client(admin_seed) -> Iterator[TestClient]:
    """Plain admin (no ``owner``) at an academy that keeps Delete owner-only."""
    yield from _client(admin_seed, "admin-only", requires_owner=True)


@pytest.fixture
def owner_delete_open_client(admin_seed) -> Iterator[TestClient]:
    """Plain admin at an academy whose owner turned the toggle OFF."""
    yield from _client(admin_seed, "admin-only", requires_owner=False)


@pytest.fixture
def owner_client_delete_required(admin_seed) -> Iterator[TestClient]:
    yield from _client(admin_seed, "admin", requires_owner=True)


@pytest.fixture
def unconfigured_policy_client(admin_seed) -> Iterator[TestClient]:
    """Plain admin at a tenant with no composed departure policy at all."""
    yield from _client(admin_seed, "admin-only", requires_owner=None)


def _enroll(client: TestClient) -> str:
    created = client.post(
        "/api/v2/admin/enrollments",
        json={
            "session_id": "sess-1",
            "student_id": "st-1",
            "parent_id": "p-1",
            "full_name": "Alice",
        },
    )
    assert created.status_code == 200, created.text
    return str(created.json()["enrollment_id"])


def _delete(client: TestClient, enrollment_id: str):
    return client.request(
        "DELETE",
        f"/api/v2/admin/enrollments/{enrollment_id}",
        json={"effective_date": "2026-05-20", "reason": "Moved away"},
    )


def test_plain_admin_cannot_delete_when_the_policy_requires_owner(
    owner_delete_required_client,
) -> None:
    """The #741 hole: this used to return 204 for any admin."""
    client = owner_delete_required_client
    enrollment_id = _enroll(client)

    response = _delete(client, enrollment_id)

    assert response.status_code == 404, response.text
    assert client.seed["enrollments"].rows[enrollment_id].status == "active"


def test_plain_admin_may_delete_once_the_owner_turns_the_toggle_off(
    owner_delete_open_client,
) -> None:
    client = owner_delete_open_client
    enrollment_id = _enroll(client)

    response = _delete(client, enrollment_id)

    assert response.status_code == 204, response.text
    assert client.seed["enrollments"].rows[enrollment_id].status != "active"


def test_owner_may_always_delete(owner_client_delete_required) -> None:
    client = owner_client_delete_required
    enrollment_id = _enroll(client)

    response = _delete(client, enrollment_id)

    assert response.status_code == 204, response.text
    assert client.seed["enrollments"].rows[enrollment_id].status != "active"


def test_an_unconfigured_policy_keeps_delete_owner_only(unconfigured_policy_client) -> None:
    """Default-safe: no composed policy means the domain default (owner-only),
    never an unguarded delete and never a 503 on a route that used to work."""
    client = unconfigured_policy_client
    enrollment_id = _enroll(client)

    response = _delete(client, enrollment_id)

    assert response.status_code == 404, response.text
    assert client.seed["enrollments"].rows[enrollment_id].status == "active"
