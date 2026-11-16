"""Migration 0233: finished outbox rows expire, unfinished ones never do (G:jobs_data_infra:8)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.shared.events.dispatcher import EventDispatcher
from backend.v2.tests.contract.test_partial_index_planner_usability import _winning_index_names

pytestmark = pytest.mark.asyncio

TTL = 90 * 24 * 60 * 60


async def test_ttl_indexes_cover_only_finished_rows(real_db) -> None:
    outbox = (await real_db["outbox_events"].index_information())["outbox_processed_ttl"]
    runs = (await real_db["event_handler_runs"].index_information())[
        "event_handler_runs_succeeded_ttl"
    ]

    assert outbox["key"] == [("processed_at", 1)]
    assert outbox["expireAfterSeconds"] == TTL
    assert outbox["partialFilterExpression"] == {"status": "processed"}
    assert runs["key"] == [("completed_at", 1)]
    assert runs["expireAfterSeconds"] == TTL
    assert runs["partialFilterExpression"] == {"status": "succeeded"}


async def test_the_claim_query_never_uses_a_ttl_index(real_db) -> None:
    """The dispatcher polls every second; a TTL index must not change its plan."""
    now = datetime.now(UTC)
    old = now - timedelta(days=200)
    rows: list[dict[str, Any]] = [
        {
            "event_id": f"done-{i}",
            "status": "processed",
            "processed": True,
            "processed_at": old,
            "created_at": old,
        }
        for i in range(50)
    ]
    rows.append(
        {
            "event_id": "todo",
            "status": "pending",
            "processed": False,
            "next_retry_at": None,
            "locked_until": None,
            "created_at": now,
        }
    )
    await real_db["outbox_events"].insert_many(rows, bypass_document_validation=True)

    captured: dict[str, Any] = {}

    class _Recorder:
        async def find_one_and_update(self, query, update, *, sort, return_document):
            captured.update(query=query, sort=sort)

    class _Db:
        def __getitem__(self, name: str) -> _Recorder:
            assert name == "outbox_events"
            return _Recorder()

    await EventDispatcher(_Db())._claim_next_event()  # type: ignore[arg-type]
    explained = await real_db.command(
        "explain",
        {"find": "outbox_events", "filter": captured["query"], "sort": dict(captured["sort"])},
        verbosity="queryPlanner",
    )

    used = _winning_index_names(explained["queryPlanner"]["winningPlan"])
    assert used, "claim query should be index-served"
    assert "outbox_processed_ttl" not in used
