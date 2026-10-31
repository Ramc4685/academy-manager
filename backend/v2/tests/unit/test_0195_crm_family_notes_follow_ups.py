"""Migration 0195 builds the family notes / follow-ups indexes, all led by
``academy_id``, the two id indexes unique, none partial; re-running is a no-op."""

from __future__ import annotations

import importlib

import mongomock_motor

_M0195 = importlib.import_module("backend.v2.migrations.0195_crm_family_notes_follow_ups")


async def test_builds_the_indexes_and_rerun_is_a_no_op() -> None:
    db = mongomock_motor.AsyncMongoMockClient()["test"]
    await _M0195.up(db)
    await _M0195.up(db)

    notes = await db["family_notes"].index_information()
    assert set(notes) == {
        "_id_",
        "family_notes_academy_note_unique",
        "family_notes_academy_parent_created",
    }
    assert notes["family_notes_academy_note_unique"]["key"] == [("academy_id", 1), ("note_id", 1)]
    assert notes["family_notes_academy_note_unique"]["unique"] is True
    assert notes["family_notes_academy_parent_created"]["key"] == [
        ("academy_id", 1),
        ("parent_id", 1),
        ("created_at", -1),
    ]

    follow_ups = await db["family_follow_ups"].index_information()
    assert set(follow_ups) == {
        "_id_",
        "family_follow_ups_academy_follow_up_unique",
        "family_follow_ups_academy_parent_created",
        "family_follow_ups_academy_assignee_status_due",
        "family_follow_ups_academy_status_due",
    }
    unique = follow_ups["family_follow_ups_academy_follow_up_unique"]
    assert unique["key"] == [("academy_id", 1), ("follow_up_id", 1)]
    assert unique["unique"] is True
    assert follow_ups["family_follow_ups_academy_assignee_status_due"]["key"] == [
        ("academy_id", 1),
        ("assignee_user_id", 1),
        ("status", 1),
        ("due_on", 1),
    ]


def test_every_index_leads_with_academy_id_and_has_no_partial_filter() -> None:
    assert _M0195.version == "0195_crm_family_notes_follow_ups"
    for _collection, _name, keys, options in _M0195.INDEXES:
        assert keys[0] == ("academy_id", 1)
        assert "partialFilterExpression" not in options
