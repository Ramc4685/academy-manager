"""Migration 0197 builds the invoice contact copy claim index: led by
``academy_id``, unique on exactly the key ``claim_digest_send`` matches
(``recipient_email``, ``digest_date``); re-running is a no-op."""

from __future__ import annotations

import importlib

import mongomock_motor

_M0197 = importlib.import_module("backend.v2.migrations.0197_invoice_contact_email_sends")


async def test_builds_the_unique_claim_index_and_rerun_is_a_no_op() -> None:
    db = mongomock_motor.AsyncMongoMockClient()["test"]
    await _M0197.up(db)
    await _M0197.up(db)

    info = await db["invoice_contact_email_sends"].index_information()
    assert set(info) == {"_id_", "invoice_contact_email_sends_key_unique"}
    index = info["invoice_contact_email_sends_key_unique"]
    assert index["key"] == [("academy_id", 1), ("recipient_email", 1), ("digest_date", 1)]
    assert index["unique"] is True
    assert "partialFilterExpression" not in index


def test_every_index_leads_with_academy_id() -> None:
    assert _M0197.version == "0197_invoice_contact_email_sends"
    for _collection, _name, keys, _options in _M0197.INDEXES:
        assert keys[0] == ("academy_id", 1)
