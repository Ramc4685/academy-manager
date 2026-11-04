"""Migration 0196 builds the family contacts / details indexes: all led by
``academy_id``, the per-family email guard partial on ``{email: {$gt: ""}}``
(never ``$type``, #878); re-running is a no-op."""

from __future__ import annotations

import importlib

import mongomock_motor

_M0196 = importlib.import_module("backend.v2.migrations.0196_crm_family_contacts")


async def test_builds_the_indexes_and_rerun_is_a_no_op() -> None:
    db = mongomock_motor.AsyncMongoMockClient()["test"]
    await _M0196.up(db)
    await _M0196.up(db)

    contacts = await db["family_contacts"].index_information()
    assert set(contacts) == {
        "_id_",
        "family_contacts_academy_contact_unique",
        "family_contacts_academy_parent_created",
        "family_contacts_academy_parent_email_unique",
    }
    unique = contacts["family_contacts_academy_contact_unique"]
    assert unique["key"] == [("academy_id", 1), ("contact_id", 1)]
    assert unique["unique"] is True
    email = contacts["family_contacts_academy_parent_email_unique"]
    assert email["key"] == [("academy_id", 1), ("parent_id", 1), ("email", 1)]
    assert email["unique"] is True
    assert email["partialFilterExpression"] == {"email": {"$gt": ""}}

    details = await db["family_details"].index_information()
    assert details["family_details_academy_parent_unique"]["key"] == [
        ("academy_id", 1),
        ("parent_id", 1),
    ]
    assert details["family_details_academy_parent_unique"]["unique"] is True


def test_every_index_leads_with_academy_id_and_no_type_filter() -> None:
    assert _M0196.version == "0196_crm_family_contacts"
    for _collection, _name, keys, options in _M0196.INDEXES:
        assert keys[0] == ("academy_id", 1)
        partial = options.get("partialFilterExpression")
        if partial is not None:
            assert "$type" not in repr(partial) and "$exists" not in repr(partial)
            assert partial == {"email": {"$gt": ""}}
