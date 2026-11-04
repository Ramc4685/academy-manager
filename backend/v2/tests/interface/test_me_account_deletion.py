"""``POST /api/v2/me/account-deletion`` (mobile M5, D1).

Mounts the ``me`` router over the real Mongo stores on mongomock with
migrations 0215 and 0216 applied, so the unique ``user_id`` on requests and
``token`` on devices hold like production. Firebase is a recording fake.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.v2.contexts.communications.application.use_cases.unregister_push_device import (
    ForgetPushDevices,
)
from backend.v2.contexts.communications.infrastructure.mongo_push_device_repo import (
    MongoPushDeviceRepository,
)
from backend.v2.contexts.identity.application.use_cases.request_account_deletion import (
    RequestAccountDeletion,
)
from backend.v2.contexts.identity.infrastructure.mongo_account_deletion_store import (
    MongoAccountDeletionStore,
)
from backend.v2.interfaces.me_routes import router as me_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.tenancy.context import _current as _tenant_var

CONFIRM = {"confirm": "DELETE"}
URL = "/api/v2/me/account-deletion"


class FakeFirebase:
    def __init__(self, *, fail: bool = False) -> None:
        self.disabled: list[str] = []
        self._fail = fail

    async def set_user_disabled(self, uid: str, disabled: bool) -> None:
        if self._fail:
            raise RuntimeError("firebase down")
        if disabled:
            self.disabled.append(uid)


@pytest.fixture
async def db() -> Any:
    mongomock_motor = pytest.importorskip("mongomock_motor")
    database = mongomock_motor.AsyncMongoMockClient()["me-account-deletion"]
    for migration in ("0215_push_devices", "0216_account_deletion_requests"):
        await importlib.import_module(f"backend.v2.migrations.{migration}").up(database)
    # One person, two academies, membership rows keyed by different aliases
    # (the invite path keys the second by firebase_uid).
    await database["users"].insert_one(
        {"user_id": "u-parent", "firebase_uid": "fb-1", "email": "p@example.com"}
    )
    await database["academy_memberships"].insert_many(
        [
            {
                "academy_id": "acad-a",
                "user_id": "u-parent",
                "roles": ["parent"],
                "status": "active",
            },
            {"academy_id": "acad-b", "user_id": "fb-1", "roles": ["parent"], "status": "active"},
            {"academy_id": "acad-a", "user_id": "u-other", "roles": ["owner"], "status": "active"},
        ]
    )
    await database["push_devices"].insert_many(
        [
            {"token": "t-a", "user_id": "u-parent", "academy_id": "acad-a"},
            {"token": "t-b", "user_id": "fb-1", "academy_id": "acad-b"},
            {"token": "t-other", "user_id": "u-other", "academy_id": "acad-a"},
        ]
    )
    return database


def _app(
    db: Any,
    *,
    firebase: FakeFirebase | None = None,
    signed_in_at: datetime | None = None,
    authenticated: bool = True,
) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(me_router, prefix="/api/v2")
    app.state.request_account_deletion = RequestAccountDeletion(
        store=MongoAccountDeletionStore(db), firebase=firebase or FakeFirebase()
    )
    app.state.forget_push_devices = ForgetPushDevices(devices=MongoPushDeviceRepository(db))

    @app.middleware("http")
    async def _tenant(request: Request, call_next):  # type: ignore[no-untyped-def]
        token = _tenant_var.set("acad-a")
        try:
            return await call_next(request)
        finally:
            _tenant_var.reset(token)

    if authenticated:
        at = signed_in_at if signed_in_at is not None else datetime.now(UTC) - timedelta(minutes=1)

        async def _claims() -> AuthClaims:
            return AuthClaims(
                user_id="u-parent",
                email="p@example.com",
                academy_id="acad-a",
                roles=("parent",),
                signed_in_at=at,
            )

        app.dependency_overrides[get_auth_claims] = _claims
    return app


async def _membership_statuses(db: Any) -> dict[tuple[str, str], str]:
    rows = await db["academy_memberships"].find({}).to_list(None)
    return {(r["academy_id"], r["user_id"]): r["status"] for r in rows}


@pytest.mark.asyncio
async def test_unauthenticated_is_401(db: Any) -> None:
    with TestClient(_app(db, authenticated=False)) as client:
        assert client.post(URL, json=CONFIRM).status_code == 401
    assert await db["account_deletion_requests"].count_documents({}) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"confirm": "delete"}, {"confirm": "yes"}])
async def test_missing_typed_confirmation_is_422(db: Any, body: dict[str, Any]) -> None:
    with TestClient(_app(db)) as client:
        assert client.post(URL, json=body).status_code == 422
    assert await db["account_deletion_requests"].count_documents({}) == 0


@pytest.mark.asyncio
async def test_an_old_sign_in_must_reauthenticate_first(db: Any) -> None:
    stale = datetime.now(UTC) - timedelta(minutes=10)
    with TestClient(_app(db, signed_in_at=stale)) as client:
        res = client.post(URL, json=CONFIRM)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "Identity.RecentSignInRequired"
    assert (await _membership_statuses(db))[("acad-a", "u-parent")] == "active"


@pytest.mark.asyncio
async def test_request_locks_the_account_in_every_academy(db: Any) -> None:
    firebase = FakeFirebase()
    with TestClient(_app(db, firebase=firebase)) as client:
        res = client.post(URL, json=CONFIRM)

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "scheduled"
    requested = datetime.fromisoformat(body["requested_at"])
    assert datetime.fromisoformat(body["execute_after"]) - requested == timedelta(days=14)

    statuses = await _membership_statuses(db)
    assert statuses[("acad-a", "u-parent")] == "removed"
    assert statuses[("acad-b", "fb-1")] == "removed"
    assert statuses[("acad-a", "u-other")] == "active"
    assert firebase.disabled == ["fb-1"]
    tokens = await db["push_devices"].distinct("token")
    assert tokens == ["t-other"]
    audits = await db["audit_logs"].find({"action": "user.deletion_requested"}).to_list(None)
    assert sorted(a["academy_id"] for a in audits) == ["acad-a", "acad-b"]
    row = await db["account_deletion_requests"].find_one({})
    assert row["user_id"] == "u-parent" and sorted(row["academy_ids"]) == ["acad-a", "acad-b"]


@pytest.mark.asyncio
async def test_a_repeat_request_returns_the_one_on_file(db: Any) -> None:
    with TestClient(_app(db)) as client:
        first = client.post(URL, json=CONFIRM).json()
        second = client.post(URL, json=CONFIRM)
    assert second.status_code == 200
    assert second.json() == first
    assert await db["account_deletion_requests"].count_documents({}) == 1


@pytest.mark.asyncio
async def test_a_retry_after_a_crash_finishes_the_lockout(db: Any) -> None:
    # The first attempt wrote the request row, then died before removing memberships.
    with TestClient(_app(db)) as client:
        client.post(URL, json=CONFIRM)
    await db["academy_memberships"].update_many(
        {"user_id": {"$in": ["u-parent", "fb-1"]}}, {"$set": {"status": "active"}}
    )
    firebase = FakeFirebase()
    with TestClient(_app(db, firebase=firebase)) as client:
        assert client.post(URL, json=CONFIRM).status_code == 200

    statuses = await _membership_statuses(db)
    assert statuses[("acad-a", "u-parent")] == "removed"
    assert statuses[("acad-b", "fb-1")] == "removed"
    assert firebase.disabled == ["fb-1"]


@pytest.mark.asyncio
async def test_a_retry_leaves_an_academy_that_restored_the_account_alone(db: Any) -> None:
    with TestClient(_app(db)) as client:
        client.post(URL, json=CONFIRM)
    # Academy B's admin re-enabled the account in the grace window.
    await MongoAccountDeletionStore(db).release_academy(aliases=["fb-1"], academy_id="acad-b")
    await db["academy_memberships"].update_one(
        {"academy_id": "acad-b", "user_id": "fb-1"}, {"$set": {"status": "active"}}
    )
    firebase = FakeFirebase()
    with TestClient(_app(db, firebase=firebase)) as client:
        assert client.post(URL, json=CONFIRM).status_code == 200

    # B is out of the request, so locking B out would keep its data and its
    # member's login gone for good; B's membership and the shared login stay.
    assert (await _membership_statuses(db))[("acad-b", "fb-1")] == "active"
    assert firebase.disabled == []
    row = await db["account_deletion_requests"].find_one({})
    assert row["academy_ids"] == ["acad-a"]


@pytest.mark.asyncio
async def test_firebase_outage_still_locks_the_account(db: Any) -> None:
    with TestClient(_app(db, firebase=FakeFirebase(fail=True))) as client:
        assert client.post(URL, json=CONFIRM).status_code == 200
    assert (await _membership_statuses(db))[("acad-b", "fb-1")] == "removed"


@pytest.mark.asyncio
async def test_the_only_owner_of_an_academy_is_refused(db: Any) -> None:
    await db["academy_memberships"].update_one(
        {"academy_id": "acad-b", "user_id": "fb-1"}, {"$set": {"roles": ["owner", "parent"]}}
    )
    with TestClient(_app(db)) as client:
        res = client.post(URL, json=CONFIRM)
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "Identity.CannotRemoveLastOwner"
    assert (await _membership_statuses(db))[("acad-a", "u-parent")] == "active"
    assert await db["account_deletion_requests"].count_documents({}) == 0

    await db["academy_memberships"].insert_one(
        {"academy_id": "acad-b", "user_id": "u-co-owner", "roles": ["owner"], "status": "active"}
    )
    with TestClient(_app(db)) as client:
        assert client.post(URL, json=CONFIRM).status_code == 200


@pytest.mark.asyncio
async def test_a_coach_with_upcoming_classes_is_refused_until_reassigned(db: Any) -> None:
    await db["academy_memberships"].update_one(
        {"academy_id": "acad-a", "user_id": "u-parent"}, {"$set": {"roles": ["coach"]}}
    )
    occurrence = {
        "academy_id": "acad-a",
        "start_at": datetime.now(UTC) + timedelta(days=2),
        "status": "scheduled",
        "assistant_coach_ids": ["fb-1"],
    }
    await db["session_occurrences"].insert_one(dict(occurrence))
    with TestClient(_app(db)) as client:
        res = client.post(URL, json=CONFIRM)
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "Identity.CoachHasFutureSessions"

    await db["session_occurrences"].update_many({}, {"$set": {"status": "cancelled"}})
    with TestClient(_app(db)) as client:
        assert client.post(URL, json=CONFIRM).status_code == 200
