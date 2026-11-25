"""The login recorder writes one tenant-scoped audit row per token (#468)."""

from __future__ import annotations

import pytest

from backend.v2.contexts.identity.infrastructure.mongo_login_audit_recorder import (
    MongoLoginAuditRecorder,
)

ACADEMY = "acad-468"


@pytest.fixture
def mongo_db(db):
    return db


async def _record(
    recorder: MongoLoginAuditRecorder, *, dedupe_key: str, provider: str = "password"
) -> None:
    await recorder.record_login(
        user_id="u-coach",
        academy_id=ACADEMY,
        membership_id="m-coach",
        roles=("coach",),
        provider=provider,
        persona="coach",
        dedupe_key=dedupe_key,
    )


@pytest.mark.asyncio
async def test_records_a_login_event_on_the_tenant_audit_trail(mongo_db) -> None:
    await _record(MongoLoginAuditRecorder(mongo_db), dedupe_key="u-coach:1")

    rows = [doc async for doc in mongo_db["audit_logs"].find({"academy_id": ACADEMY})]

    assert len(rows) == 1
    assert rows[0]["action"] == "user_logged_in"
    assert rows[0]["actor_id"] == "u-coach"
    assert rows[0]["entity_type"] == "user"
    assert rows[0]["entity_id"] == "u-coach"
    assert rows[0]["metadata"]["provider"] == "password"
    assert rows[0]["metadata"]["persona"] == "coach"


@pytest.mark.asyncio
async def test_one_token_writes_one_row_however_many_requests_it_makes(mongo_db) -> None:
    recorder = MongoLoginAuditRecorder(mongo_db)

    await _record(recorder, dedupe_key="u-coach:1")
    await _record(recorder, dedupe_key="u-coach:1")
    await _record(recorder, dedupe_key="u-coach:1")

    rows = [doc async for doc in mongo_db["audit_logs"].find({"academy_id": ACADEMY})]
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_a_fresh_token_writes_a_fresh_row(mongo_db) -> None:
    recorder = MongoLoginAuditRecorder(mongo_db)

    await _record(recorder, dedupe_key="u-coach:1")
    await _record(recorder, dedupe_key="u-coach:2")

    rows = [doc async for doc in mongo_db["audit_logs"].find({"academy_id": ACADEMY})]
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_a_new_session_stamps_last_login_at_on_the_users_row(mongo_db) -> None:
    # The parent digest decides "has this parent ever signed in?" from
    # users.last_login_at; nothing wrote it before, so every parent looked
    # never-activated and got a fresh auto-login link every day.
    await mongo_db["users"].insert_one({"user_id": "u-coach", "email": "c@example.com"})

    await _record(MongoLoginAuditRecorder(mongo_db), dedupe_key="u-coach:1")

    user = await mongo_db["users"].find_one({"user_id": "u-coach"})
    assert user["last_login_at"] is not None


@pytest.mark.asyncio
async def test_the_audit_row_survives_a_failing_users_write(mongo_db) -> None:
    # Regression: the users update ran first, so its failure lost the audit row.
    class _BrokenUsers:
        async def update_one(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("users write failed")

    class _Db:
        def __getitem__(self, name: str) -> object:
            return _BrokenUsers() if name == "users" else mongo_db[name]

    with pytest.raises(RuntimeError):
        await _record(MongoLoginAuditRecorder(_Db()), dedupe_key="u-coach:3")

    assert await mongo_db["audit_logs"].count_documents({"actor_id": "u-coach"}) == 1


@pytest.mark.asyncio
async def test_last_login_is_stamped_on_a_row_keyed_by_auth_uid(mongo_db) -> None:
    await mongo_db["users"].insert_one({"user_id": "other", "auth_uid": "u-coach"})

    await _record(MongoLoginAuditRecorder(mongo_db), dedupe_key="u-coach:4")

    assert (await mongo_db["users"].find_one({"auth_uid": "u-coach"}))["last_login_at"]
