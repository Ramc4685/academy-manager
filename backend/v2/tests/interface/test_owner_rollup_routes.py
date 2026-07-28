"""UIM11 — owner cross-academy rollup: scoping, flag, and persona behaviour.

The load-bearing assertion here is that the rollup's academy set comes from
the caller's own `owner` memberships and from nowhere else — in particular
that the request tenant can neither add nor remove an academy.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.v2.composition.owner import (
    MembershipOwnerAcademyDirectory,
    OwnerComposition,
)
from backend.v2.contexts.billing.application.ports import AcademyFinancialSnapshot
from backend.v2.contexts.billing.application.use_cases.owner_rollup import (
    GetOwnerFinancialRollup,
)
from backend.v2.contexts.identity.domain.models import AcademyMembership
from backend.v2.interfaces.owner.router import router as owner_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims


class _FakeMembershipsRepo:
    def __init__(self, memberships: list[AcademyMembership]) -> None:
        self._memberships = memberships

    async def list_memberships_for_user(self, user_id: str) -> list[AcademyMembership]:
        return [m for m in self._memberships if m.user_id == user_id]


class _FakeAcademyRepo:
    def __init__(self, names: dict[str, dict[str, str]]) -> None:
        self._names = names

    async def find_by_id(self, academy_id: str) -> dict[str, str] | None:
        return self._names.get(academy_id)


class _FakeSnapshotReader:
    """Returns a distinct, identifiable figure per academy."""

    def __init__(self, per_academy: dict[str, AcademyFinancialSnapshot]) -> None:
        self._per_academy = per_academy
        self.seen: list[str] = []
        self.months_seen: list[tuple[str, ...] | None] = []

    async def read(
        self, *, academy_id: str, months: tuple[str, ...] | None = None
    ) -> AcademyFinancialSnapshot:
        self.seen.append(academy_id)
        self.months_seen.append(months)
        return self._per_academy.get(academy_id, AcademyFinancialSnapshot())


def _membership(
    academy_id: str, roles: tuple[str, ...], status: str = "active"
) -> AcademyMembership:
    return AcademyMembership(
        membership_id=f"m-{academy_id}",
        academy_id=academy_id,
        user_id="u-owner",
        roles=roles,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
    )


_SNAPSHOTS = {
    "academy-a": AcademyFinancialSnapshot(
        revenue_by_month={"2026-06": 1_000, "2026-07": 2_000},
        collected_cents=3_000,
        outstanding_cents=500,
        outstanding_invoice_count=2,
    ),
    "academy-b": AcademyFinancialSnapshot(
        revenue_by_month={"2026-07": 4_000},
        collected_cents=4_000,
        outstanding_cents=100,
        outstanding_invoice_count=1,
    ),
    "academy-c": AcademyFinancialSnapshot(
        revenue_by_month={"2026-07": 99_999},
        collected_cents=99_999,
        outstanding_cents=99_999,
        outstanding_invoice_count=9,
    ),
}


def _make_app(
    memberships: list[AcademyMembership],
    *,
    tenant_academy_id: str = "academy-a",
    mount: bool = True,
    wire_state: bool = True,
    authenticated: bool = True,
) -> tuple[FastAPI, _FakeSnapshotReader]:
    app = FastAPI()
    if mount:
        app.include_router(owner_router, prefix="/api/v2")
    reader = _FakeSnapshotReader(_SNAPSHOTS)
    if wire_state:
        app.state.owner = OwnerComposition(
            get_rollup=GetOwnerFinancialRollup(
                academies=MembershipOwnerAcademyDirectory(
                    _FakeMembershipsRepo(memberships),  # type: ignore[arg-type]
                    _FakeAcademyRepo(
                        {
                            "academy-a": {"display_name": "Academy A"},
                            "academy-b": {"display_name": "Academy B"},
                            "academy-c": {"display_name": "Academy C"},
                        }
                    ),  # type: ignore[arg-type]
                ),
                snapshots=reader,
            )
        )

    async def _claims() -> AuthClaims:
        return AuthClaims(
            user_id="u-owner",
            email="owner@example.com",
            academy_id=tenant_academy_id,
            roles=("admin",),
        )

    if authenticated:
        app.dependency_overrides[get_auth_claims] = _claims
    return app, reader


def test_rollup_covers_every_owned_academy_and_sums_totals() -> None:
    app, reader = _make_app(
        [
            _membership("academy-a", ("admin", "owner")),
            _membership("academy-b", ("owner",)),
        ]
    )
    with TestClient(app) as client:
        response = client.get("/api/v2/owner/rollup")

    assert response.status_code == 200
    body = response.json()
    assert [row["academy_id"] for row in body["academies"]] == ["academy-a", "academy-b"]
    assert body["totals"]["academy_count"] == 2
    assert body["totals"]["revenue_by_month"] == {"2026-06": 1_000, "2026-07": 6_000}
    assert body["totals"]["collected_cents"] == 7_000
    assert body["totals"]["outstanding_cents"] == 600
    assert body["totals"]["outstanding_invoice_count"] == 3
    assert sorted(reader.seen) == ["academy-a", "academy-b"]


def test_single_owner_membership_returns_one_academy() -> None:
    app, _ = _make_app([_membership("academy-b", ("owner",))])
    with TestClient(app) as client:
        response = client.get("/api/v2/owner/rollup")

    assert response.status_code == 200
    body = response.json()
    assert [row["academy_id"] for row in body["academies"]] == ["academy-b"]
    assert body["totals"]["collected_cents"] == 4_000


def test_non_owner_memberships_are_excluded_from_scope() -> None:
    """Admin in A, owner in B → the rollup covers B only, never A."""

    app, reader = _make_app(
        [
            _membership("academy-a", ("admin", "coach")),
            _membership("academy-b", ("owner",)),
        ]
    )
    with TestClient(app) as client:
        response = client.get("/api/v2/owner/rollup")

    assert response.status_code == 200
    assert [row["academy_id"] for row in response.json()["academies"]] == ["academy-b"]
    assert reader.seen == ["academy-b"]


@pytest.mark.parametrize("status", ["invited", "suspended", "removed"])
def test_only_active_owner_memberships_grant_access(status: str) -> None:
    """`invited` matters most: that is where an unaccepted grant sits."""

    app, _ = _make_app([_membership("academy-a", ("owner",), status=status)])
    with TestClient(app) as client:
        response = client.get("/api/v2/owner/rollup")

    assert response.status_code == 404


def test_unauthenticated_request_is_rejected_before_the_use_case() -> None:
    app, reader = _make_app(
        [_membership("academy-a", ("owner",))],
        authenticated=False,
    )
    with TestClient(app) as client:
        response = client.get("/api/v2/owner/rollup")

    assert response.status_code == 401
    assert reader.seen == []


def test_user_without_owner_membership_gets_404() -> None:
    app, _ = _make_app([_membership("academy-a", ("admin",))])
    with TestClient(app) as client:
        response = client.get("/api/v2/owner/rollup")

    assert response.status_code == 404


@pytest.mark.parametrize("tenant_academy_id", ["academy-a", "academy-b", "academy-c"])
def test_tenant_header_cannot_widen_or_narrow_the_academy_set(tenant_academy_id: str) -> None:
    """The caller owns A and B only. Whichever tenant the request resolves to —
    including academy-c, which they do not own — the rollup is exactly A+B."""

    app, reader = _make_app(
        [
            _membership("academy-a", ("owner",)),
            _membership("academy-b", ("owner",)),
        ],
        tenant_academy_id=tenant_academy_id,
    )
    with TestClient(app) as client:
        response = client.get(
            "/api/v2/owner/rollup",
            headers={"X-Academy-Id": "academy-c"},
        )

    assert response.status_code == 200
    assert [row["academy_id"] for row in response.json()["academies"]] == [
        "academy-a",
        "academy-b",
    ]
    assert "academy-c" not in reader.seen


def test_routes_absent_when_flag_off() -> None:
    """Flag off → router never mounted, so the path 404s."""

    app, _ = _make_app([_membership("academy-a", ("owner",))], mount=False)
    with TestClient(app) as client:
        response = client.get("/api/v2/owner/rollup")

    assert response.status_code == 404


def test_unwired_composition_404s_rather_than_500s() -> None:
    app, _ = _make_app([_membership("academy-a", ("owner",))], wire_state=False)
    with TestClient(app) as client:
        response = client.get("/api/v2/owner/rollup")

    assert response.status_code == 404


def test_months_filter_is_passed_through() -> None:
    app, reader = _make_app([_membership("academy-a", ("owner",))])
    with TestClient(app) as client:
        response = client.get("/api/v2/owner/rollup?months=2026-07")

    assert response.status_code == 200
    assert reader.months_seen == [("2026-07",)]
