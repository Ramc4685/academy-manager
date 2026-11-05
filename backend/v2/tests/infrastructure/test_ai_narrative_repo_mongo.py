"""``ai_narratives`` and the ``ai_calls`` approver stamp on mongomock: tenant
isolation, one row per key, decide-only-pending, approved-only reads."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import mongomock_motor
from backend.v2.contexts.ai.domain.models import DEFAULT_MODEL, AiCallRecord
from backend.v2.contexts.ai.domain.narrative import AiNarrative
from backend.v2.contexts.ai.infrastructure.mongo_ai_call_repo import MongoAiCallRepository
from backend.v2.contexts.ai.infrastructure.mongo_ai_narrative_repo import (
    MongoAiNarrativeRepository,
)
from backend.v2.shared.tenancy import tenant_scope
from pymongo.errors import DuplicateKeyError

NOW = datetime(2026, 11, 4, 18, 0, tzinfo=UTC)


def _db() -> Any:
    return mongomock_motor.AsyncMongoMockClient()["test"]


def _row(narrative_id: str, text: str = "Aarav did well.", **over: Any) -> AiNarrative:
    base: dict[str, Any] = dict(
        narrative_id=narrative_id,
        student_id="s-aarav",
        for_date="2026-11-04",
        kind="evening_wins",
        text=text,
        status="pending_review",
        prompt_version="progress-narrative-v1",
        call_id="call-1",
        created_by="coach-1",
        created_at=NOW,
    )
    return AiNarrative(**{**base, **over})


async def test_rows_are_invisible_to_another_academy() -> None:
    db = _db()
    with tenant_scope("acad-a"):
        row = await MongoAiNarrativeRepository(db).upsert_draft(_row("n1"))
    with tenant_scope("acad-b"):
        repo_b = MongoAiNarrativeRepository(db)
        assert await repo_b.get("n1") is None
        assert await repo_b.list_pending("2026-11-04", None) == []
        assert (
            await repo_b.decide("n1", status="approved", text=None, approver="b", decided_at=NOW)
            is None
        )
        # B's own draft for the same student id and day is a separate row.
        await repo_b.upsert_draft(_row("n1b"))
    with tenant_scope("acad-a"):
        repo_a = MongoAiNarrativeRepository(db)
        assert await repo_a.get("n1") == row
        assert [r.narrative_id for r in await repo_a.list_pending("2026-11-04", "coach-1")] == [
            "n1"
        ]
    assert await db["ai_narratives"].count_documents({}) == 2


async def test_a_second_draft_for_the_same_key_replaces_the_first() -> None:
    db = _db()
    with tenant_scope("acad-a"):
        repo = MongoAiNarrativeRepository(db)
        await repo.upsert_draft(_row("n1", status="approved", approver="coach-1"))
        second = await repo.upsert_draft(_row("n2", text="Second try."))
        assert second.narrative_id == "n2" and second.status == "pending_review"
        assert await repo.get("n1") is None
        # A different kind for the same day is its own row.
        await repo.upsert_draft(_row("n3", kind="report_card"))
    assert await db["ai_narratives"].count_documents({}) == 2
    docs = [d async for d in db["ai_narratives"].find({"kind": "evening_wins"})]
    assert [(d["narrative_id"], d["text"], d["academy_id"]) for d in docs] == [
        ("n2", "Second try.", "acad-a")
    ]


async def test_decide_only_moves_a_pending_row_and_keeps_the_text_unless_edited() -> None:
    db = _db()
    with tenant_scope("acad-a"):
        repo = MongoAiNarrativeRepository(db)
        await repo.upsert_draft(_row("n1"))
        rejected = await repo.decide(
            "n1", status="rejected", text=None, approver=None, decided_at=NOW
        )
        assert rejected is not None
        assert (rejected.status, rejected.text, rejected.decided_at) == (
            "rejected",
            "Aarav did well.",
            NOW,
        )
        assert (
            await repo.decide("n1", status="approved", text="x", approver="c", decided_at=NOW)
            is None
        )
        await repo.upsert_draft(_row("n2", student_id="s-diya"))
        approved = await repo.decide(
            "n2", status="approved", text="Diya flew.", approver="coach-1", decided_at=NOW
        )
        assert approved is not None and (approved.text, approved.approver) == (
            "Diya flew.",
            "coach-1",
        )


async def test_approved_text_for_returns_only_approved_rows_of_the_day_and_kind() -> None:
    db = _db()
    with tenant_scope("acad-a"):
        repo = MongoAiNarrativeRepository(db)
        await repo.upsert_draft(_row("p", student_id="s-pending"))
        await repo.upsert_draft(_row("r", student_id="s-rejected", status="rejected"))
        await repo.upsert_draft(
            _row("a", student_id="s-approved", status="approved", approver="c", text="Approved.")
        )
        await repo.upsert_draft(
            _row(
                "y", student_id="s-approved", status="approved", for_date="2026-11-03", text="Old."
            )
        )
        ids = ["s-pending", "s-rejected", "s-approved", "s-none"]
        assert await repo.approved_text_for(ids, "2026-11-04", "evening_wins") == {
            "s-approved": "Approved."
        }
        assert await repo.approved_text_for(ids, "2026-11-04", "report_card") == {}
    with tenant_scope("acad-b"):
        assert (
            await MongoAiNarrativeRepository(db).approved_text_for(
                ids, "2026-11-04", "evening_wins"
            )
            == {}
        )


async def test_ai_calls_record_returns_the_id_and_set_approver_is_tenant_scoped() -> None:
    db = _db()
    record = AiCallRecord(
        feature="progress_narrative",
        prompt_version="progress-narrative-v1",
        model=DEFAULT_MODEL,
        input_tokens=1,
        output_tokens=1,
        cost_cents=1,
        approver=None,
        created_at=NOW,
    )
    with tenant_scope("acad-a"):
        await MongoAiCallRepository(db).record(record)
    call_id = record.call_id
    with tenant_scope("acad-b"):
        assert await MongoAiCallRepository(db).set_approver(call_id, "intruder") is False
    with tenant_scope("acad-a"):
        assert await MongoAiCallRepository(db).set_approver(call_id, "coach-1") is True
    doc = await db["ai_calls"].find_one({"call_id": call_id})
    assert doc is not None and (doc["approver"], doc["academy_id"]) == ("coach-1", "acad-a")


async def test_upsert_draft_retries_once_when_a_racing_draft_wins_the_unique_key() -> None:
    db = _db()
    with tenant_scope("acad-a"):
        repo = MongoAiNarrativeRepository(db)
        real = repo._find_one_and_update
        attempts: list[int] = []

        async def racing(*args: Any, **kwargs: Any) -> Any:
            attempts.append(1)
            if len(attempts) == 1:
                raise DuplicateKeyError("E11000 duplicate key")
            return await real(*args, **kwargs)

        repo._find_one_and_update = racing  # type: ignore[method-assign]
        row = await repo.upsert_draft(_row("n1"))
    assert (row.narrative_id, len(attempts)) == ("n1", 2)
    assert await db["ai_narratives"].count_documents({}) == 1
