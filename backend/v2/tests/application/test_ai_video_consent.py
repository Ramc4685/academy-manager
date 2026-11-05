"""Per-child AI/video consent (Phase 3 E1) on the real Mongo repo (mongomock).

Grant, revoke, the ``consent_ai_video`` read path (false by default, after
revoke, and for the placeholder text), and tenant isolation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import mongomock_motor
import pytest

from backend.v2.contexts.onboarding.application.use_cases.ai_video_consent import (
    AI_VIDEO_CONSENT_TEXT_VERSION,
    ConsentAiVideo,
    ListAdminAiVideoConsents,
    ParentAiVideoConsent,
)
from backend.v2.contexts.onboarding.domain.errors import (
    AiVideoConsentIncomplete,
    AiVideoConsentTextChanged,
    WaiverStudentNotFound,
)
from backend.v2.contexts.onboarding.infrastructure.mongo_ai_video_consent_repo import (
    MongoAiVideoConsentRepository,
)
from backend.v2.shared.tenancy import tenant_scope

NOW = datetime(2026, 11, 5, 18, 0, tzinfo=UTC)
#: A stand-in for the counsel-reviewed text the owner ships later.
REVIEWED = "ai_video_consent_v1"


async def _db() -> Any:
    db = mongomock_motor.AsyncMongoMockClient()["test"]
    await db["students"].insert_many(
        [
            {"academy_id": "acad-a", "student_id": "s-asha", "full_name": "Asha Rao",
             "parent_id": "p-rao", "status": "active"},
            {"academy_id": "acad-a", "student_id": "s-dev", "full_name": "Dev Rao",
             "parent_user_id": "p-rao", "status": "active"},
            {"academy_id": "acad-a", "student_id": "s-other", "full_name": "Other Kid",
             "parent_id": "p-other", "status": "active"},
            {"academy_id": "acad-b", "student_id": "s-asha", "full_name": "Asha B",
             "parent_id": "p-rao", "status": "active"},
        ]
    )  # fmt: skip
    return db


def _parent(db: Any, version: str = AI_VIDEO_CONSENT_TEXT_VERSION) -> ParentAiVideoConsent:
    return ParentAiVideoConsent(
        consents=MongoAiVideoConsentRepository(db), clock=lambda: NOW, text_version=version
    )


def _gate(db: Any, version: str = AI_VIDEO_CONSENT_TEXT_VERSION) -> ConsentAiVideo:
    return ConsentAiVideo(consents=MongoAiVideoConsentRepository(db), text_version=version)


async def _grant(db: Any, student_id: str = "s-asha", version: str = REVIEWED) -> None:
    with tenant_scope("acad-a"):
        await _parent(db, version).grant(
            parent_id="p-rao",
            student_id=student_id,
            text_version=version,
            consent=True,
            signer_email="rao@example.com",
        )


async def test_every_child_starts_with_no_consent_and_the_gate_is_false() -> None:
    db = await _db()
    with tenant_scope("acad-a"):
        view = await _parent(db).get(parent_id="p-rao")
    assert view.placeholder is True
    assert view.text_version == "ai_video_consent_v0_placeholder"
    assert [(c.student_id, c.status) for c in view.children] == [
        ("s-asha", "none"),
        ("s-dev", "none"),
    ]
    assert await _gate(db, REVIEWED)("acad-a", "s-asha") is False


async def test_grant_records_version_time_and_parent() -> None:
    db = await _db()
    await _grant(db)
    with tenant_scope("acad-a"):
        view = await _parent(db, REVIEWED).get(parent_id="p-rao")
    asha = next(c for c in view.children if c.student_id == "s-asha")
    assert (asha.status, asha.text_version, asha.accepted_at, asha.accepted_by) == (
        "granted",
        REVIEWED,
        NOW,
        "p-rao",
    )
    doc = await db["ai_video_consents"].find_one({"student_id": "s-asha"})
    assert doc["academy_id"] == "acad-a"
    assert doc["accepted_by_email"] == "rao@example.com"
    assert await _gate(db, REVIEWED)("acad-a", "s-asha") is True
    # Only the child consented for; a sibling stays off.
    assert await _gate(db, REVIEWED)("acad-a", "s-dev") is False


async def test_placeholder_consent_never_authorizes() -> None:
    db = await _db()
    await _grant(db, version=AI_VIDEO_CONSENT_TEXT_VERSION)
    doc = await db["ai_video_consents"].find_one({"student_id": "s-asha"})
    assert doc["status"] == "granted"
    assert await _gate(db)("acad-a", "s-asha") is False
    # Nor does it carry over once the reviewed text replaces the placeholder.
    assert await _gate(db, REVIEWED)("acad-a", "s-asha") is False


async def test_revoke_turns_the_gate_off_and_is_recorded() -> None:
    db = await _db()
    await _grant(db)
    with tenant_scope("acad-a"):
        view = await _parent(db, REVIEWED).revoke(parent_id="p-rao", student_id="s-asha")
    asha = next(c for c in view.children if c.student_id == "s-asha")
    assert (asha.status, asha.revoked_at) == ("revoked", NOW)
    assert await _gate(db, REVIEWED)("acad-a", "s-asha") is False
    doc = await db["ai_video_consents"].find_one({"student_id": "s-asha"})
    assert doc["revoked_by"] == "p-rao"
    assert [h["action"] for h in doc["history"]] == ["granted", "revoked"]

    # A re-grant keeps the record that consent was once withdrawn.
    await _grant(db)
    doc = await db["ai_video_consents"].find_one({"student_id": "s-asha"})
    assert [h["action"] for h in doc["history"]] == ["granted", "revoked", "granted"]
    assert doc["revoked_at"] is None
    assert await _gate(db, REVIEWED)("acad-a", "s-asha") is True


async def test_revoke_without_a_consent_is_a_no_op() -> None:
    db = await _db()
    with tenant_scope("acad-a"):
        await _parent(db).revoke(parent_id="p-rao", student_id="s-asha")
    assert await db["ai_video_consents"].count_documents({}) == 0


async def test_another_familys_child_is_not_found() -> None:
    db = await _db()
    with tenant_scope("acad-a"), pytest.raises(WaiverStudentNotFound):
        await _parent(db, REVIEWED).grant(
            parent_id="p-rao",
            student_id="s-other",
            text_version=REVIEWED,
            consent=True,
            signer_email=None,
        )
    with tenant_scope("acad-a"), pytest.raises(WaiverStudentNotFound):
        await _parent(db).revoke(parent_id="p-rao", student_id="s-other")
    assert await db["ai_video_consents"].count_documents({}) == 0


async def test_unticked_box_and_stale_text_are_refused() -> None:
    db = await _db()
    with tenant_scope("acad-a"):
        with pytest.raises(AiVideoConsentIncomplete):
            await _parent(db).grant(
                parent_id="p-rao",
                student_id="s-asha",
                text_version=AI_VIDEO_CONSENT_TEXT_VERSION,
                consent=False,
                signer_email=None,
            )
        with pytest.raises(AiVideoConsentTextChanged):
            await _parent(db, REVIEWED).grant(
                parent_id="p-rao",
                student_id="s-asha",
                text_version=AI_VIDEO_CONSENT_TEXT_VERSION,
                consent=True,
                signer_email=None,
            )
    assert await db["ai_video_consents"].count_documents({}) == 0


async def test_consent_is_isolated_per_academy() -> None:
    db = await _db()
    await _grant(db)
    # Same student id in academy B: no consent, and B's revoke cannot touch A.
    assert await _gate(db, REVIEWED)("acad-b", "s-asha") is False
    with tenant_scope("acad-b"):
        view = await _parent(db, REVIEWED).get(parent_id="p-rao")
        assert [(c.student_id, c.status) for c in view.children] == [("s-asha", "none")]
        await _parent(db, REVIEWED).revoke(parent_id="p-rao", student_id="s-asha")
        assert (
            await ListAdminAiVideoConsents(consents=MongoAiVideoConsentRepository(db)).execute()
            == []
        )
    assert await _gate(db, REVIEWED)("acad-a", "s-asha") is True


async def test_mutating_with_another_academys_scope_leaves_the_row_untouched() -> None:
    db = await _db()
    await _grant(db)
    with tenant_scope("acad-b"):
        await MongoAiVideoConsentRepository(db).save_revoke(
            "s-asha", revoked_at=NOW, revoked_by="intruder"
        )
    doc = await db["ai_video_consents"].find_one({"academy_id": "acad-a", "student_id": "s-asha"})
    assert doc["status"] == "granted" and doc["revoked_by"] is None


async def test_admin_lists_each_childs_status_with_names() -> None:
    db = await _db()
    await _grant(db, "s-dev")
    await _grant(db, "s-asha")
    with tenant_scope("acad-a"):
        await _parent(db, REVIEWED).revoke(parent_id="p-rao", student_id="s-asha")
        rows = await ListAdminAiVideoConsents(consents=MongoAiVideoConsentRepository(db)).execute()
    assert [(r.student_name, r.status) for r in rows] == [
        ("Asha Rao", "revoked"),
        ("Dev Rao", "granted"),
    ]


async def test_gate_is_false_for_missing_ids() -> None:
    db = await _db()
    await _grant(db)
    assert await _gate(db, REVIEWED)("", "s-asha") is False
    assert await _gate(db, REVIEWED)("acad-a", "") is False
