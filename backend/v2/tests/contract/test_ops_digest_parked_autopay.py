"""Ops digest counts autopay ladders stuck parked on our side (L1 A7-1), on real Mongo."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.shared.observability.ops_digest import collect_ops_digest, render_ops_digest

NOW = datetime(2026, 11, 15, 7, 0, tzinfo=UTC)


def _state(
    invoice_id: str, *, reason: str | None, parked_since, next_attempt_at=None, status="active"
):
    return {
        "academy_id": "acad",
        "invoice_id": invoice_id,
        "status": status,
        "next_attempt_at": next_attempt_at,
        "suppression_reason": reason,
        "parked_since": parked_since,
    }


@pytest.mark.asyncio
async def test_parked_autopay_charges_counted_only_when_stale_and_on_our_side(db) -> None:
    await db["dunning_states"].insert_many(
        [
            _state(
                "stale-fault",
                reason="charge_technical_failure",
                parked_since=NOW - timedelta(hours=5),
            ),
            _state(
                "fresh-fault",
                reason="charge_technical_failure",
                parked_since=NOW - timedelta(minutes=20),
            ),
            _state(
                "ach-settling", reason="payment_processing", parked_since=NOW - timedelta(days=2)
            ),
            _state("scheduled", reason=None, parked_since=None, next_attempt_at=NOW),
            _state("legacy-no-stamp", reason="connected_account_not_ready", parked_since=None),
        ]
    )

    snapshot = await collect_ops_digest(db, now=NOW)

    # A row parked before parked_since existed counts too: it is stuck right now.
    assert snapshot.dunning_parked_stale == 2
    assert snapshot.has_attention_items
    _subject, body = render_ops_digest(snapshot)
    assert "Autopay charges parked" in body
