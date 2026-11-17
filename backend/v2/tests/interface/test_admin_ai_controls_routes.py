"""``/admin/ai/controls`` (L13): owner-only AI caps and coach-review switch.

The route tests use a fake store; the composition tests run
``AcademyAiControls`` on mongomock and check that the readers the features use
(``AcademyAiCapLookup``, ``AcademyCoachReviewSwitch``) see what it writes, that
an untouched academy reads exactly the old defaults, and that each change is
one audit row naming the owner."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

from backend.v2.composition.ai import (
    CAPPABLE_FEATURES,
    AcademyAiCapLookup,
    AcademyAiControls,
    AiControls,
)
from backend.v2.composition.ai_narratives import AcademyCoachReviewSwitch
from backend.v2.contexts.ai.application.use_cases.record_ai_call import (
    DEFAULT_MONTHLY_CALL_CAP,
)
from backend.v2.contexts.ai.infrastructure.mongo_ai_controls_audit import MongoAiControlsAudit
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
    MongoAcademyRepository,
)
from backend.v2.interfaces.admin.ai_controls_routes import router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.shared.tenancy import tenant_scope

ROUTE = "/api/v2/admin/ai/controls"
BODY = {
    "monthly_call_cap": 400,
    "daily_call_caps": {"technique_observation": 30},
    "coach_review_narratives": False,
}


class FakeControls:
    def __init__(self) -> None:
        self.value = AiControls(
            monthly_call_cap=DEFAULT_MONTHLY_CALL_CAP,
            daily_call_caps={},
            coach_review_narratives=True,
        )
        self.by: str | None = None

    async def get(self) -> AiControls:
        return self.value

    async def set(self, controls: AiControls, *, user_id: str) -> AiControls:
        self.value, self.by = controls, user_id
        return controls


def _client(role: str, controls: FakeControls) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api/v2/admin")
    app.state.ai = SimpleNamespace(controls=controls)
    roles: tuple[str, ...] = ("admin", "owner") if role == "owner" else (role,)
    app.dependency_overrides[get_auth_claims] = lambda: AuthClaims(
        user_id=f"u-{role}",
        email=f"{role}@example.com",
        academy_id="acad",
        roles=roles,  # type: ignore[arg-type]
    )
    return TestClient(app)


def test_owner_reads_defaults_and_saves_new_limits() -> None:
    controls = FakeControls()
    client = _client("owner", controls)
    assert client.get(ROUTE).json() == {
        "monthly_call_cap": DEFAULT_MONTHLY_CALL_CAP,
        "daily_call_caps": {},
        "coach_review_narratives": True,
        "features": list(CAPPABLE_FEATURES),
    }
    response = client.put(ROUTE, json=BODY)
    assert response.status_code == 200, response.text
    assert response.json()["coach_review_narratives"] is False
    assert controls.by == "u-owner"
    assert controls.value.daily_call_caps == {"technique_observation": 30}


@pytest.mark.parametrize(
    "body",
    [
        {**BODY, "monthly_call_cap": -1},
        {**BODY, "monthly_call_cap": 5001},
        {**BODY, "daily_call_caps": {"made_up": 3}},
        {**BODY, "daily_call_caps": {"placeholder": 3}},
        {**BODY, "daily_call_caps": {"skill_ladder": 1001}},
    ],
)
def test_out_of_range_or_unknown_limits_are_refused(body: dict[str, object]) -> None:
    controls = FakeControls()
    assert _client("owner", controls).put(ROUTE, json=body).status_code == 422
    assert controls.by is None


@pytest.mark.parametrize("role", ["admin", "coach"])
def test_only_the_owner_sees_the_routes(role: str) -> None:
    controls = FakeControls()
    client = _client(role, controls)
    assert client.get(ROUTE).status_code == 404
    assert client.put(ROUTE, json=BODY).status_code == 404
    assert controls.by is None


@pytest.fixture()
def db():  # type: ignore[no-untyped-def]
    return AsyncMongoMockClient()["ai_controls"]


async def test_an_untouched_academy_reads_the_same_defaults_as_the_features(db) -> None:  # type: ignore[no-untyped-def]
    await db.academies.insert_one({"academy_id": "blno"})
    academies = MongoAcademyRepository(db)
    with tenant_scope("blno"):
        controls = await AcademyAiControls(academies, MongoAiControlsAudit(db)).get()
        lookup = AcademyAiCapLookup(academies)
        assert controls.monthly_call_cap == await lookup.monthly_cap() == DEFAULT_MONTHLY_CALL_CAP
        assert controls.daily_call_caps == {}
        assert await lookup.daily_cap("technique_observation") is None
        assert controls.coach_review_narratives is True
        assert await AcademyCoachReviewSwitch(academies).coach_review_required() is True


async def test_a_save_reaches_the_readers_and_writes_one_audit_row(db) -> None:  # type: ignore[no-untyped-def]
    await db.academies.insert_one({"academy_id": "acad-a", "ai": {"share_import_values": True}})
    await db.academies.insert_one({"academy_id": "acad-b"})
    academies = MongoAcademyRepository(db)
    controls = AcademyAiControls(academies, MongoAiControlsAudit(db))
    wanted = AiControls(
        monthly_call_cap=400,
        daily_call_caps={"technique_observation": 30},
        coach_review_narratives=False,
    )
    with tenant_scope("acad-a"):
        assert await controls.set(wanted, user_id="owner-1") == wanted
        await controls.set(wanted, user_id="owner-1")  # unchanged: no second row
        lookup = AcademyAiCapLookup(academies)
        assert await lookup.monthly_cap() == 400
        assert await lookup.daily_cap("technique_observation") == 30
        assert await AcademyCoachReviewSwitch(academies).coach_review_required() is False
        with pytest.raises(ValueError):
            await controls.set(
                AiControls(
                    monthly_call_cap=1, daily_call_caps={"x": 1}, coach_review_narratives=True
                ),
                user_id="owner-1",
            )

    doc = await db.academies.find_one({"academy_id": "acad-a"})
    assert doc["ai"]["share_import_values"] is True  # sibling settings untouched
    rows = await db.audit_logs.find({}).to_list(None)
    assert len(rows) == 1
    row = rows[0]
    assert row["academy_id"] == "acad-a" and row["actor_id"] == "owner-1"
    assert row["action"] == "ai_controls.changed"
    assert row["changed_keys"] == [
        "coach_review_narratives",
        "daily_call_caps",
        "monthly_call_cap",
    ]
    assert "ai" not in (await db.academies.find_one({"academy_id": "acad-b"}))
