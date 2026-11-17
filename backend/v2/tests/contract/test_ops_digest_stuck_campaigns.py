"""Ops digest counts email campaigns stuck in ``sending`` (L11), on real Mongo."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.shared.observability.ops_digest import collect_ops_digest, render_ops_digest

NOW = datetime(2026, 11, 17, 7, 0, tzinfo=UTC)


def _campaign(campaign_id: str, *, status: str, age: timedelta) -> dict:
    return {
        "academy_id": "acad",
        "campaign_id": campaign_id,
        "status": status,
        "created_at": NOW - age,
        "dispatch": "inline",
    }


@pytest.mark.asyncio
async def test_only_campaigns_sending_for_over_30_minutes_count(real_db) -> None:
    await real_db["message_campaigns"].insert_many(
        [
            _campaign("lost", status="sending", age=timedelta(hours=3)),
            _campaign("draining", status="sending", age=timedelta(minutes=5)),
            _campaign("done", status="sent", age=timedelta(days=1)),
        ]
    )

    snapshot = await collect_ops_digest(real_db, now=NOW)

    assert snapshot.campaigns_stuck_sending == 1
    assert snapshot.has_attention_items
    _subject, body = render_ops_digest(snapshot)
    assert "Email campaigns stuck sending" in body
