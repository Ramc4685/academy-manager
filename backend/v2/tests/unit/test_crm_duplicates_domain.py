"""Pure rules of the People CRM duplicate warning (Phase 4c): normalisation,
the phone spellings looked up, the family-row matcher and masking."""

from __future__ import annotations

from backend.v2.contexts.crm.domain.duplicates import (
    build_probe,
    family_record_matches,
    mask_email,
    mask_phone,
    phone_matches,
    probe_email,
    probe_phone_variants,
)
from backend.v2.contexts.crm.domain.family_index import FamilyRecord


def _record(**overrides: object) -> FamilyRecord:
    fields: dict[str, object] = {
        "family_id": "p-1",
        "parent_name": "Zoë Testparent",
        "email": "Zoe.Parent@Example.test",
        "phone": "(555) 010-2030",
        "has_account": True,
        "children": (),
        "stage": "active",
    }
    fields.update(overrides)
    return FamilyRecord(**fields)  # type: ignore[arg-type]


def test_email_is_trimmed_and_lower_cased_and_must_look_like_an_email() -> None:
    assert probe_email("  Zoe.Parent@Example.TEST ") == "zoe.parent@example.test"
    assert probe_email("no-at-sign") is None
    assert probe_email("two@@example.test") is None
    assert probe_email("@example.test") is None
    assert probe_email("") is None
    assert probe_email(None) is None


def test_north_american_phone_is_looked_up_with_and_without_the_country_code() -> None:
    assert probe_phone_variants("(555) 010-2030") == ("5550102030", "15550102030")
    assert probe_phone_variants("+1 555 010 2030") == ("5550102030", "15550102030")
    assert probe_phone_variants("+44 20 7946 0958") == ("442079460958",)
    assert probe_phone_variants("010-20") == ()
    assert probe_phone_variants("1" * 16) == ()
    assert probe_phone_variants(None) == ()


def test_stored_phone_matches_in_any_punctuation() -> None:
    probe = build_probe(phone="555.010.2030")
    assert phone_matches("+1 (555) 010-2030", probe)
    assert phone_matches("5550102030", probe)
    assert not phone_matches("5550102031", probe)
    assert not phone_matches(None, probe)


def test_empty_probe() -> None:
    assert build_probe().is_empty
    assert build_probe(email=" ", phone="12", name="  ").is_empty
    assert not build_probe(name="Someone").is_empty


def test_family_row_matches_on_email_phone_and_exact_name() -> None:
    record = _record()
    assert family_record_matches(record, build_probe(email="zoe.parent@example.test")) == ("email",)
    assert family_record_matches(record, build_probe(phone="15550102030")) == ("phone",)
    assert family_record_matches(record, build_probe(name="zoe  TESTPARENT")) == ("name",)
    assert family_record_matches(record, build_probe(name="Zoe")) == ()
    both = build_probe(email="ZOE.PARENT@example.test", phone="555-010-2030")
    assert family_record_matches(record, both) == ("email", "phone")
    assert family_record_matches(_record(email=None, phone=None), both) == ()


def test_masking_shows_enough_to_recognise_and_no_more() -> None:
    assert mask_email("Zoe.Parent@Example.test") == "zo***@example.test"
    assert mask_email("abc@example.test") == "a***@example.test"
    assert mask_email("not-an-email") is None
    assert mask_email(None) is None
    assert mask_phone("(555) 010-2030") == "•••-2030"
    assert mask_phone("12") is None
    assert mask_phone(None) is None
