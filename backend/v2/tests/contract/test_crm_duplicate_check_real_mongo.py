"""The People CRM duplicate warning on a real ``mongod`` (Phase 4c, migration 0197).

``real_db`` replays every migration, so the lookups run against the
production indexes. Wired exactly as ``composition/people_duplicates.py``
wires it (real family index, real repositories, identity's member lookup).
Checks:

* a family is matched by email case-insensitively, by phone in any format
  (with or without the +1 country code), and by exact name;
* inquiries (``crm_contacts``), family contacts and staff users match too,
  each with its link, and contact details come back masked;
* nothing of another academy ever comes back: not its families, inquiries,
  family contacts, nor a user whose only membership is there;
* empty or unusable input answers ``[]`` without a query;
* every lookup the use case issues is served by an index (``explain()``).

Synthetic names only. Skipped without a ``mongod``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.composition.people_duplicates import compose_admin_people_duplicates
from backend.v2.contexts.crm.application.use_cases.find_possible_duplicates import (
    DuplicateCheckQuery,
)
from backend.v2.contexts.crm.domain.duplicates import DuplicateMatch
from backend.v2.shared.tenancy import tenant_scope

A = "acad-dupes-a"
B = "acad-dupes-b"
NOW = datetime(2026, 9, 24, 15, 0, tzinfo=UTC)


async def _seed(db: Any) -> None:
    await db["academies"].insert_many(
        [
            {"academy_id": A, "display_name": "Alpha Academy", "timezone": "America/Chicago"},
            {"academy_id": B, "display_name": "Bravo Academy", "timezone": "America/Chicago"},
        ]
    )
    await db["users"].insert_many(
        [
            {
                "user_id": "a-parent",
                "academy_id": A,
                "display_name": "Alpha Testparent",
                "email": "Alpha.Parent@Example.test",
                "normalized_email": "alpha.parent@example.test",
                "phone": "(555) 010-2030",
                "roles": ["parent"],
            },
            {
                "user_id": "a-coach",
                "academy_id": A,
                "display_name": "Alpha Testcoach",
                "email": "alpha.coach@example.test",
                "normalized_email": "alpha.coach@example.test",
                "roles": ["coach"],
            },
            {
                "user_id": "b-parent",
                "academy_id": B,
                "display_name": "Bravo Testparent",
                "email": "bravo.parent@example.test",
                "normalized_email": "bravo.parent@example.test",
                "phone": "555-020-3040",
                "roles": ["parent"],
            },
            {
                # A coach of academy B only.
                "user_id": "b-coach",
                "academy_id": B,
                "display_name": "Bravo Testcoach",
                "email": "bravo.coach@example.test",
                "normalized_email": "bravo.coach@example.test",
                "roles": ["coach"],
            },
        ]
    )
    await db["academy_memberships"].insert_many(
        [
            {
                "academy_id": A,
                "membership_id": "m-a-parent",
                "user_id": "a-parent",
                "roles": ["parent"],
                "status": "active",
            },
            {
                "academy_id": A,
                "membership_id": "m-a-coach",
                "user_id": "a-coach",
                "roles": ["coach"],
                "status": "active",
            },
            {
                "academy_id": B,
                "membership_id": "m-b-parent",
                "user_id": "b-parent",
                "roles": ["parent"],
                "status": "active",
            },
            {
                "academy_id": B,
                "membership_id": "m-b-coach",
                "user_id": "b-coach",
                "roles": ["coach"],
                "status": "active",
            },
        ]
    )
    await db["students"].insert_many(
        [
            {
                "academy_id": A,
                "student_id": "a-kid",
                "parent_id": "a-parent",
                "full_name": "Alpha Kiddo",
            },
            {
                "academy_id": B,
                "student_id": "b-kid",
                "parent_id": "b-parent",
                "full_name": "Bravo Kiddo",
            },
        ]
    )
    await db["family_contacts"].insert_many(
        [
            {
                "academy_id": A,
                "contact_id": "a-fc",
                "parent_id": "a-parent",
                "name": "Alpha Secondparent",
                "relationship": "parent",
                "email": "second.alpha@example.test",
                "phone": "+1 555 010 7070",
                "phone_digits": "15550107070",
                "created_by": "a-admin",
                "created_at": NOW,
                "updated_at": NOW,
            },
            {
                "academy_id": B,
                "contact_id": "b-fc",
                "parent_id": "b-parent",
                "name": "Bravo Secondparent",
                "relationship": "parent",
                "email": "shared.household@example.test",
                "phone_digits": "5550409090",
                "created_by": "b-admin",
                "created_at": NOW,
                "updated_at": NOW,
            },
        ]
    )
    consent = {"contact_about_request": True, "marketing": False, "captured_at": NOW}
    await db["crm_contacts"].insert_many(
        [
            {
                "academy_id": A,
                "contact_id": "a-lead",
                "name": "Alpha Inquirer",
                "email": "lead.alpha@example.test",
                "phone_digits": "5550105050",
                "source": "whatsapp_or_phone",
                "pipeline_status": "lead",
                "consent": consent,
                "created_at": NOW,
                "updated_at": NOW,
            },
            {
                "academy_id": A,
                "contact_id": "a-lead-no-email",
                "name": "Alpha Phoneonly",
                "email": None,
                "phone_digits": "5550106060",
                "source": "other",
                "pipeline_status": "lead",
                "consent": consent,
                "created_at": NOW,
                "updated_at": NOW,
            },
            {
                "academy_id": B,
                "contact_id": "b-lead",
                "name": "Bravo Inquirer",
                "email": "shared.household@example.test",
                "phone_digits": "5550105050",
                "source": "website",
                "pipeline_status": "trial",
                "consent": consent,
                "created_at": NOW,
                "updated_at": NOW,
            },
        ]
    )


async def _check(db: Any, academy: str, **fields: str | None) -> list[DuplicateMatch]:
    services = compose_admin_people_duplicates(db)
    with tenant_scope(academy):
        return await services.find.execute(academy, DuplicateCheckQuery(**fields))


def _kinds(matches: list[DuplicateMatch]) -> set[tuple[str, str]]:
    return {(match.kind, match.record_id) for match in matches}


async def test_family_matches_by_email_case_insensitively(real_db: Any) -> None:
    await _seed(real_db)
    matches = await _check(real_db, A, email="  ALPHA.parent@example.TEST ")
    assert _kinds(matches) == {("family", "a-parent")}
    family = matches[0]
    assert family.display_name == "Alpha Testparent"
    assert family.link == "/admin/families/a-parent"
    assert family.matched_on == ("email",)
    assert family.email_masked == "al***@example.test"
    assert family.phone_masked == "•••-2030"


@pytest.mark.parametrize(
    "phone", ["555-010-2030", "(555) 010 2030", "+1 555.010.2030", "15550102030"]
)
async def test_family_matches_by_phone_in_any_format(real_db: Any, phone: str) -> None:
    await _seed(real_db)
    matches = await _check(real_db, A, phone=phone)
    assert ("family", "a-parent") in _kinds(matches)


async def test_family_contact_matches_by_phone_with_or_without_country_code(
    real_db: Any,
) -> None:
    await _seed(real_db)
    for phone in ("555 010 7070", "+1 (555) 010-7070"):
        matches = await _check(real_db, A, phone=phone)
        assert _kinds(matches) == {("family_contact", "a-fc")}
        assert matches[0].link == "/admin/families/a-parent"
        assert matches[0].matched_on == ("phone",)


async def test_inquiry_matches_by_email_and_phone_and_merges_reasons(real_db: Any) -> None:
    await _seed(real_db)
    matches = await _check(real_db, A, email="Lead.Alpha@example.test", phone="555-010-5050")
    assert _kinds(matches) == {("inquiry", "a-lead")}
    assert matches[0].matched_on == ("email", "phone")
    assert matches[0].link is None  # not linked to a family yet
    assert matches[0].email_masked == "le***@example.test"
    phone_only = await _check(real_db, A, phone="5550106060")
    assert _kinds(phone_only) == {("inquiry", "a-lead-no-email")}


async def test_staff_user_matches_only_through_a_membership_here(real_db: Any) -> None:
    await _seed(real_db)
    coach = await _check(real_db, A, email="alpha.coach@example.test")
    assert _kinds(coach) == {("user", "a-coach")}
    assert coach[0].link == "/admin/users/a-coach"
    # A parent who is a member is reported once, as their family.
    parent = await _check(real_db, A, email="alpha.parent@example.test")
    assert _kinds(parent) == {("family", "a-parent")}


async def test_exact_name_matches_a_family_but_a_prefix_does_not(real_db: Any) -> None:
    await _seed(real_db)
    assert _kinds(await _check(real_db, A, name="alpha  TESTPARENT")) == {("family", "a-parent")}
    assert await _check(real_db, A, name="Alpha Test") == []


async def test_nothing_of_another_academy_ever_comes_back(real_db: Any) -> None:
    await _seed(real_db)
    probes: list[dict[str, str]] = [
        {"email": "bravo.parent@example.test"},  # B's family
        {"phone": "555-020-3040"},  # B's family phone
        {"name": "Bravo Testparent"},  # B's family name
        {"email": "bravo.coach@example.test"},  # a user whose only membership is B
        {"email": "shared.household@example.test"},  # B's inquiry and family contact
        {"phone": "5550409090"},  # B's family contact phone
    ]
    for probe in probes:
        assert await _check(real_db, A, **probe) == [], probe
    # The same phone exists in both academies: A sees only its own inquiry.
    both = await _check(real_db, A, phone="5550105050")
    assert _kinds(both) == {("inquiry", "a-lead")}
    # And B sees only B's.
    from_b = await _check(real_db, B, phone="5550105050")
    assert _kinds(from_b) == {("inquiry", "b-lead")}


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"email": "", "phone": "", "name": ""},
        {"email": "   ", "phone": "  ", "name": " "},
        {"email": "not-an-email", "phone": "12-34"},
    ],
)
async def test_empty_or_unusable_input_answers_nothing(
    real_db: Any, fields: dict[str, str]
) -> None:
    await _seed(real_db)
    assert await _check(real_db, A, **fields) == []


def _index_names(plan: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    if plan.get("indexName"):
        found.add(plan["indexName"])
    for key in ("inputStage", "queryPlan"):
        if isinstance(plan.get(key), dict):
            found |= _index_names(plan[key])
    for child in plan.get("inputStages", []) or []:
        found |= _index_names(child)
    return found


@pytest.mark.parametrize(
    ("collection", "filter_", "index"),
    [
        (
            "crm_contacts",
            {"email": "lead.alpha@example.test", "academy_id": A},
            "crm_contacts_academy_email_lookup",
        ),
        (
            "crm_contacts",
            {"phone_digits": "5550105050", "academy_id": A},
            "crm_contacts_academy_phone_lookup",
        ),
        (
            "family_contacts",
            {"email": "second.alpha@example.test", "academy_id": A},
            "family_contacts_academy_email_lookup",
        ),
        (
            "family_contacts",
            {"phone_digits": "15550107070", "academy_id": A},
            "family_contacts_academy_phone_lookup",
        ),
        (
            "users",
            {"normalized_email": "alpha.coach@example.test"},
            "users_normalized_email_unique",
        ),
        (
            "academy_memberships",
            {"academy_id": A, "user_id": {"$in": ["a-coach"]}},
            "membership_academy_user_unique",
        ),
    ],
)
async def test_every_lookup_is_served_by_an_index(
    real_db: Any, collection: str, filter_: dict[str, Any], index: str
) -> None:
    await _seed(real_db)
    explained = await real_db.command(
        "explain", {"find": collection, "filter": filter_}, verbosity="queryPlanner"
    )
    plan = explained["queryPlanner"]["winningPlan"]
    assert index in _index_names(plan), plan
