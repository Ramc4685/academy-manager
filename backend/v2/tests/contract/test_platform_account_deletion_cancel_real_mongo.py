"""Support-only restore on a real ``mongod`` (PR #1115).

``POST /api/v2/platform/account-deletions/{id}/cancel`` over the real stores:
the person's own request locked them out of two academies; only platform
support can cancel it, and that restores both academies and the login.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from backend.v2.contexts.identity.application.use_cases.cancel_account_deletion import (
    CancelAccountDeletion,
)
from backend.v2.contexts.identity.application.use_cases.request_account_deletion import (
    RequestAccountDeletion,
    RequestAccountDeletionCommand,
)
from backend.v2.contexts.identity.infrastructure.mongo_account_deletion_store import (
    MongoAccountDeletionStore,
)
from backend.v2.contexts.platform.audit.application.use_cases import PlatformAuditService
from backend.v2.contexts.platform.audit.infrastructure.mongo_platform_audit_repo import (
    MongoPlatformAuditRepository,
)
from backend.v2.interfaces.platform.router import router as platform_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

pytestmark = pytest.mark.asyncio

NOW = datetime.now(UTC)
A, B = "acad-a", "acad-b"


class FakeFirebase:
    """The admin adapter's switch: last write wins, like Firebase's ``disabled``."""

    def __init__(self) -> None:
        self.disabled: dict[str, bool] = {}

    async def set_user_disabled(self, uid: str, disabled: bool) -> None:
        self.disabled[uid] = disabled


SUPPORT = AuthClaims(
    user_id="support-1",
    email="support@example.com",
    academy_id="platform-control",
    platform_roles=("platform_support",),
)
ACADEMY_ADMIN = AuthClaims(
    user_id="admin-b", email="admin@example.com", academy_id=B, roles=("admin", "owner")
)


async def _request_deletion(db: Any, firebase: FakeFirebase) -> str:
    await db["users"].insert_one({"user_id": "u1", "firebase_uid": "fb1", "email": "p@x.com"})
    await db["academy_memberships"].insert_many(
        [
            {
                "membership_id": "ma",
                "academy_id": A,
                "user_id": "u1",
                "roles": ["parent"],
                "status": "active",
            },
            {
                "membership_id": "mb",
                "academy_id": B,
                "user_id": "fb1",
                "roles": ["parent"],
                "status": "suspended",
            },
        ]
    )
    request = await RequestAccountDeletion(
        store=MongoAccountDeletionStore(db), firebase=firebase
    ).execute(
        RequestAccountDeletionCommand(user_id="u1", email="p@x.com", signed_in_at=NOW), now=NOW
    )
    assert firebase.disabled == {"fb1": True}
    assert set(await db["academy_memberships"].distinct("status")) == {"removed"}
    return request.request_id


def _app(db: Any, firebase: FakeFirebase, claims: AuthClaims) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(platform_router, prefix="/api/v2")
    app.state.cancel_account_deletion = CancelAccountDeletion(
        store=MongoAccountDeletionStore(db), firebase=firebase
    )
    app.state.platform_audit = PlatformAuditService(audit_events=MongoPlatformAuditRepository(db))
    app.dependency_overrides[get_auth_claims] = lambda: claims
    return app


async def _cancel(db: Any, firebase: FakeFirebase, claims: AuthClaims, request_id: str):
    transport = httpx.ASGITransport(app=_app(db, firebase, claims))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.post(
            f"/api/v2/platform/account-deletions/{request_id}/cancel",
            json={"reason": "confirmed with the parent by phone"},
        )


async def _statuses(db: Any) -> dict[str, str]:
    return {d["academy_id"]: d["status"] async for d in db["academy_memberships"].find({})}


async def test_support_cancel_restores_every_academy_and_the_login(real_db: Any) -> None:
    firebase = FakeFirebase()
    request_id = await _request_deletion(real_db, firebase)

    res = await _cancel(real_db, firebase, SUPPORT, request_id)

    assert res.status_code == 200, res.text
    body = res.json()
    assert sorted(body.pop("academy_ids")) == [A, B]
    assert body == {"request_id": request_id, "user_id": "u1", "firebase_enabled": True}
    assert await _statuses(real_db) == {A: "active", B: "suspended"}
    assert firebase.disabled == {"fb1": False}
    assert await real_db["account_deletion_requests"].count_documents({}) == 0
    audits = await real_db["platform_audit_events"].find({}).to_list(None)
    assert sorted(a["academy_id"] for a in audits) == [A, B]
    assert {a["action"] for a in audits} == {"account_deletion.cancelled_by_support"}
    assert {a["actor_user_id"] for a in audits} == {"support-1"}
    assert {a["platform_actor_role"] for a in audits} == {"platform_support"}


async def test_an_academy_admin_cannot_call_the_support_route(real_db: Any) -> None:
    firebase = FakeFirebase()
    request_id = await _request_deletion(real_db, firebase)

    res = await _cancel(real_db, firebase, ACADEMY_ADMIN, request_id)

    assert res.status_code == 404
    assert await real_db["account_deletion_requests"].count_documents({}) == 1
    assert set((await _statuses(real_db)).values()) == {"removed"}
    assert firebase.disabled == {"fb1": True}
    assert await real_db["platform_audit_events"].count_documents({}) == 0


@pytest.mark.parametrize("started", ["claimed", "failed_attempt"])
async def test_support_cancel_is_refused_once_the_erasure_started(
    real_db: Any, started: str
) -> None:
    firebase = FakeFirebase()
    request_id = await _request_deletion(real_db, firebase)
    store = MongoAccountDeletionStore(real_db)
    claim_at = NOW + timedelta(days=15)
    assert await store.claim(request_id, now=claim_at) is not None
    if started == "failed_attempt":
        await store.record_failure(request_id, step="family", error="boom", now=claim_at)

    res = await _cancel(real_db, firebase, SUPPORT, request_id)

    assert res.status_code == 409
    assert res.json()["error"]["code"] == "Identity.AccountDeletionInProgress"
    assert await store.request_exists(request_id)
    assert set((await _statuses(real_db)).values()) == {"removed"}
    assert firebase.disabled == {"fb1": True}
    assert await real_db["platform_audit_events"].count_documents({}) == 0


async def test_an_unknown_request_is_404(real_db: Any) -> None:
    res = await _cancel(real_db, FakeFirebase(), SUPPORT, "nope")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "Identity.AccountDeletionRequestNotFound"
