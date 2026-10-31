"""``apply_blno_mongo`` upsert selectors are tenant-scoped for per-academy ids (#881).

The script does ``replace_one(selector, doc, upsert=True)``; a selector without
``academy_id`` on a collection whose id is unique only per academy (0189)
resolves a row across every tenant.
"""

from __future__ import annotations

import pytest

from backend.scripts.apply_blno_mongo import (
    COMPOSITE_FILTERS,
    IDENTITY_FIELDS,
    build_upsert_filter,
)

PER_ACADEMY = {
    "academy_settings": "settings_id",
    "expenses": "expense_id",
    "waiver_templates": "waiver_template_id",
}


@pytest.mark.parametrize(("collection", "id_field"), sorted(PER_ACADEMY.items()))
def test_selector_carries_academy_id(collection: str, id_field: str) -> None:
    doc = {"academy_id": "acad-a", id_field: "x-1", "other": 1}

    selector = build_upsert_filter(collection, doc)

    assert selector == {"academy_id": "acad-a", id_field: "x-1"}
    assert collection not in IDENTITY_FIELDS
    assert COMPOSITE_FILTERS[collection][0] == "academy_id"


@pytest.mark.parametrize(("collection", "id_field"), sorted(PER_ACADEMY.items()))
def test_same_id_under_two_academies_selects_two_rows(collection: str, id_field: str) -> None:
    a = build_upsert_filter(collection, {"academy_id": "acad-a", id_field: "x-1"})
    b = build_upsert_filter(collection, {"academy_id": "acad-b", id_field: "x-1"})

    assert a != b


@pytest.mark.parametrize(("collection", "id_field"), sorted(PER_ACADEMY.items()))
def test_doc_without_academy_id_is_refused(collection: str, id_field: str) -> None:
    with pytest.raises(ValueError, match="academy_id"):
        build_upsert_filter(collection, {id_field: "x-1"})


def test_waiver_templates_key_on_waiver_template_id_not_legacy_template_id() -> None:
    # The old ``template_id`` entry never matched a v2 waiver template, so
    # every row failed "Missing identity fields" instead of writing.
    ok = build_upsert_filter(
        "waiver_templates", {"academy_id": "acad-a", "waiver_template_id": "wt-1"}
    )
    assert ok == {"academy_id": "acad-a", "waiver_template_id": "wt-1"}
    with pytest.raises(ValueError, match="waiver_template_id"):
        build_upsert_filter("waiver_templates", {"academy_id": "acad-a", "template_id": "wt-1"})
