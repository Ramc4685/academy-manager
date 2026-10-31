"""Outbox: pull_unprocessed/mark_processed must not exist.

Issue #536 — these two methods filtered/wrote only the legacy `processed`
flag, never the `status` field the dispatcher's claim path actually reads.
A caller using them to "replay" unprocessed events would re-deliver events
the dispatcher already claimed (status pending/retry), since a document can
have status="processed" while processed stays False forever, and vice
versa. Nothing in the codebase calls them, so the fix is to delete the dead,
unsafe surface rather than repair it.
"""

from __future__ import annotations

from backend.v2.shared.events.outbox import MongoOutbox, Outbox


def test_outbox_protocol_has_no_pull_unprocessed() -> None:
    assert not hasattr(Outbox, "pull_unprocessed")


def test_outbox_protocol_has_no_mark_processed() -> None:
    assert not hasattr(Outbox, "mark_processed")


def test_mongo_outbox_has_no_pull_unprocessed() -> None:
    assert not hasattr(MongoOutbox, "pull_unprocessed")


def test_mongo_outbox_has_no_mark_processed() -> None:
    assert not hasattr(MongoOutbox, "mark_processed")
