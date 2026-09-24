"""Migration 0200 backfills ``fee_model`` = flat_monthly and null agreement
fields on legacy academies, never fabricates an acceptance, and is a no-op
on re-run."""

from __future__ import annotations

import importlib

import mongomock_motor

_M0200 = importlib.import_module("backend.v2.migrations.0200_tenant_fee_model_and_agreement")


async def test_backfills_defaults_and_rerun_is_a_no_op() -> None:
    db = mongomock_motor.AsyncMongoMockClient()["test"]
    await db["academies"].insert_many(
        [
            {"academy_id": "acad_a", "display_name": "Synthetic A"},
            {
                "academy_id": "acad_b",
                "display_name": "Synthetic B",
                "fee_model": "flat_monthly",
                "platform_agreement_version": "v1",
                "platform_agreement_accepted_at": None,
                "platform_agreement_accepted_by": "owner@example.test",
            },
        ]
    )

    await _M0200.up(db)
    await _M0200.up(db)

    a = await db["academies"].find_one({"academy_id": "acad_a"})
    assert a is not None
    assert a["fee_model"] == "flat_monthly"
    assert all(a[field] is None for field in _M0200.AGREEMENT_FIELDS)
    b = await db["academies"].find_one({"academy_id": "acad_b"})
    assert b is not None
    assert b["platform_agreement_version"] == "v1"
    assert b["platform_agreement_accepted_by"] == "owner@example.test"


def test_version_matches_filename() -> None:
    assert _M0200.version == "0200_tenant_fee_model_and_agreement"
