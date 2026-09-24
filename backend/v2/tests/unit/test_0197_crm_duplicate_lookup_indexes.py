"""Migration 0197 builds the duplicate-warning lookup indexes: every one led by
``academy_id``, partial on ``{field: {$gt: ""}}`` (never ``$type``, #878),
non-unique (a shared household email is warned about, never refused);
re-running is a no-op."""

from __future__ import annotations

import importlib

import mongomock_motor

_M0197 = importlib.import_module("backend.v2.migrations.0197_crm_duplicate_lookup_indexes")


async def test_builds_the_indexes_and_rerun_is_a_no_op() -> None:
    db = mongomock_motor.AsyncMongoMockClient()["test"]
    await _M0197.up(db)
    await _M0197.up(db)

    contacts = await db["crm_contacts"].index_information()
    assert contacts["crm_contacts_academy_email_lookup"]["key"] == [
        ("academy_id", 1),
        ("email", 1),
    ]
    assert contacts["crm_contacts_academy_phone_lookup"]["key"] == [
        ("academy_id", 1),
        ("phone_digits", 1),
    ]
    family = await db["family_contacts"].index_information()
    assert family["family_contacts_academy_email_lookup"]["partialFilterExpression"] == {
        "email": {"$gt": ""}
    }
    assert family["family_contacts_academy_phone_lookup"]["partialFilterExpression"] == {
        "phone_digits": {"$gt": ""}
    }
    for info in (*contacts.values(), *family.values()):
        assert not info.get("unique")


def test_every_index_leads_with_academy_id_and_filters_with_gt_empty() -> None:
    assert _M0197.version == "0197_crm_duplicate_lookup_indexes"
    assert len(_M0197.INDEXES) == 4
    for _collection, _name, keys, options in _M0197.INDEXES:
        assert keys[0] == ("academy_id", 1)
        field = keys[1][0]
        partial = options["partialFilterExpression"]
        assert partial == {field: {"$gt": ""}}
        assert "$type" not in repr(partial) and "$exists" not in repr(partial)
        assert "unique" not in options
