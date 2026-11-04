"""Offline payment methods on the academy record (hardcoded-values row 22).

BLNO pin: until an owner saves a choice, every academy (BLNO included) reads
all six methods in the order the payment dialogs have always listed them,
with cash first (the dialogs' default). That holds whatever list the record
already carries, because the only writers before this setting were
``upsert_defaults`` (``["cash", "check"]``) and seed scripts: no backfill.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import mongomock_motor
import pytest

from backend.v2.contexts.identity.application.academy_payment_methods import (
    GetAcademyPaymentMethods,
    SetAcademyPaymentMethods,
)
from backend.v2.contexts.identity.domain.errors import InvalidManualPaymentMethods
from backend.v2.contexts.identity.domain.manual_payment_methods import (
    MANUAL_PAYMENT_METHODS,
    effective_manual_methods,
    normalize_manual_methods,
)
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import MongoAcademyRepository

ALL_SIX = ["cash", "check", "zelle", "venmo", "bank_transfer", "other"]
BLNO_PROD = "acad_blno_badminton"
BLNO_LOCAL = "blno"
OTHER = "acad-riverside"
NOW = datetime(2026, 9, 28, 15, 0, tzinfo=UTC)


def test_canonical_set_and_order_is_the_dialogs_list() -> None:
    assert list(MANUAL_PAYMENT_METHODS) == ALL_SIX


@pytest.mark.parametrize(
    "doc",
    [
        None,
        {},
        {"academy_id": BLNO_PROD},
        # upsert_defaults' old default, never an owner's choice
        {"academy_id": BLNO_PROD, "manual_methods": ["cash", "check"]},
        # local seed's list, never an owner's choice
        {"academy_id": BLNO_LOCAL, "manual_methods": ["cash", "check", "zelle"]},
        {"academy_id": BLNO_PROD, "manual_methods": []},
    ],
)
def test_an_academy_without_an_owner_choice_offers_all_six(doc: dict[str, Any] | None) -> None:
    assert effective_manual_methods(doc) == ALL_SIX


def test_an_owner_choice_is_read_in_canonical_order() -> None:
    doc = {"manual_methods": ["zelle", "cash"], "manual_methods_updated_at": NOW}
    assert effective_manual_methods(doc) == ["cash", "zelle"]


def test_a_corrupt_owner_choice_never_offers_nothing() -> None:
    doc = {"manual_methods": ["wire"], "manual_methods_updated_at": NOW}
    assert effective_manual_methods(doc) == ALL_SIX


def test_normalize_dedupes_and_orders() -> None:
    assert normalize_manual_methods(["other", "cash", "cash"]) == ["cash", "other"]


@pytest.mark.parametrize("bad", [[], ["cash", "bitcoin"], ["Cash"]])
def test_normalize_refuses_unknown_or_empty(bad: list[str]) -> None:
    with pytest.raises(InvalidManualPaymentMethods):
        normalize_manual_methods(bad)


async def _repo() -> tuple[Any, MongoAcademyRepository]:
    db = mongomock_motor.AsyncMongoMockClient()["manual_payment_methods"]
    await db["academies"].insert_many(
        [
            # BLNO as production may hold it today: the old upsert default.
            {"academy_id": BLNO_PROD, "manual_methods": ["cash", "check"]},
            {"academy_id": OTHER, "display_name": "Riverside"},
        ]
    )
    return db, MongoAcademyRepository(db)


async def test_blno_reads_all_six_with_no_backfill() -> None:
    _db, repo = await _repo()
    assert await GetAcademyPaymentMethods(repo).execute(BLNO_PROD) == ALL_SIX


async def test_a_new_academy_reads_all_six() -> None:
    db = mongomock_motor.AsyncMongoMockClient()["manual_payment_methods_new"]
    repo = MongoAcademyRepository(db)
    doc = await repo.upsert_defaults("acad-new")
    assert "manual_methods" not in doc
    assert await GetAcademyPaymentMethods(repo).execute("acad-new") == ALL_SIX


async def test_saving_a_choice_marks_it_and_touches_one_academy_only() -> None:
    db, repo = await _repo()
    saved = await SetAcademyPaymentMethods(repo, clock=lambda: NOW).execute(
        OTHER, ["zelle", "cash"], actor_id="u-owner"
    )

    assert saved == ["cash", "zelle"]
    stored = await db["academies"].find_one({"academy_id": OTHER})
    assert stored["manual_methods"] == ["cash", "zelle"]
    assert stored["manual_methods_updated_by"] == "u-owner"
    assert stored["manual_methods_updated_at"] is not None
    assert await GetAcademyPaymentMethods(repo).execute(OTHER) == ["cash", "zelle"]
    # Tenant isolation: BLNO's record and reading are unchanged.
    blno = await db["academies"].find_one({"academy_id": BLNO_PROD})
    assert blno["manual_methods"] == ["cash", "check"]
    assert "manual_methods_updated_at" not in blno
    assert await GetAcademyPaymentMethods(repo).execute(BLNO_PROD) == ALL_SIX


async def test_saving_refuses_an_invalid_choice_and_writes_nothing() -> None:
    db, repo = await _repo()
    with pytest.raises(InvalidManualPaymentMethods):
        await SetAcademyPaymentMethods(repo).execute(OTHER, [], actor_id="u-owner")
    stored = await db["academies"].find_one({"academy_id": OTHER})
    assert "manual_methods" not in stored
