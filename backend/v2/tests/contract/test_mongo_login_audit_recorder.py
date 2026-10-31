"""The login recorder writes one tenant-scoped audit row per token (#468)."""

from __future__ import annotations

import pytest

from backend.v2.contexts.identity.infrastructure.mongo_login_audit_recorder import (
    MongoLoginAuditRecorder,
)

ACADEMY = "acad-468"


@pytest.fixture
def mongo_db():
    mongomock_motor = pytest.importorskip("mongomock_motor")
    client = mongomock_motor.AsyncMongoMockClient()
    return client["test_db"]


async def _record(recorder: MongoLoginAuditRecorder, *, dedupe_key: str) -> None:
    await recorder.record_login(
        user_id="u-coach",
        academy_id=ACADEMY,
        membership_id="m-coach",
        roles=("coach",),
        provider="password",
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
