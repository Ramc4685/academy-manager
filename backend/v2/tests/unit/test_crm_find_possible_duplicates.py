"""``FindPossibleDuplicates`` over in-memory stand-ins (People CRM Phase 4c).

Store behaviour, tenancy and index use are proven on a real ``mongod`` in
``contract/test_crm_duplicate_check_real_mongo.py``; this pins the merge
rules: one answer per record with every reason, contact matches ahead of
name-only matches, at most five, a failed family index skipped rather than
failing the form, and no lookup at all for an empty probe.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from backend.v2.contexts.crm.application.family_index import FamilyIndexUnavailable
from backend.v2.contexts.crm.application.use_cases.find_possible_duplicates import (
    DuplicateCheckQuery,
    FindPossibleDuplicates,
)
from backend.v2.contexts.crm.domain.family_contacts import FamilyContact
from backend.v2.contexts.crm.domain.family_index import FamilyIndex, FamilyRecord
from backend.v2.contexts.crm.domain.models import ContactConsent, CrmContact

A = "acad-a"
NOW = datetime(2026, 9, 24, 15, 0, tzinfo=UTC)


def _family(family_id: str, name: str, email: str | None = None) -> FamilyRecord:
    return FamilyRecord(
        family_id=family_id,
        parent_name=name,
        email=email,
        phone=None,
        has_account=True,
        children=(),
        stage="active",
    )


class _Index:
    def __init__(self, families: list[FamilyRecord], *, fail: bool = False) -> None:
        self.families = families
        self.fail = fail
        self.calls: list[str] = []

    async def build(self, academy_id: str) -> FamilyIndex:
        self.calls.append(academy_id)
        if self.fail:
            raise FamilyIndexUnavailable("students unavailable")
        return FamilyIndex(
            academy_id=academy_id,
            generated_at=NOW,
            families=tuple(self.families),
            family_by_alias={f.family_id: f.family_id for f in self.families},
        )


class _Lookup:
    """Mirrors the repositories: exact equality on the stored field, limit honoured."""

    def __init__(self, rows: list) -> None:  # type: ignore[type-arg]
        self.rows = rows
        self.calls: list[tuple[str, str]] = []

    async def find_by_email(self, email: str, *, limit: int = 5) -> list:  # type: ignore[type-arg]
        self.calls.append(("email", email))
        return [row for row in self.rows if row.email == email][:limit]

    async def find_by_phone_digits(self, digits: str, *, limit: int = 5) -> list:  # type: ignore[type-arg]
        self.calls.append(("phone", digits))
        return [row for row in self.rows if row.phone_digits == digits][:limit]


@dataclass(frozen=True)
class _Member:
    user_id: str
    display_name: str | None
    email: str | None
    phone: str | None


class _Members:
    def __init__(self, members: dict[tuple[str, str], _Member]) -> None:
        self.members = members
        self.calls: list[tuple[str, str]] = []

    async def find_member_by_email(self, academy_id: str, email: str) -> _Member | None:
        self.calls.append((academy_id, email))
        return self.members.get((academy_id, email))


def _inquiry(contact_id: str, *, email: str | None, phone: str | None) -> CrmContact:
    return CrmContact(
        contact_id=contact_id,
        academy_id=A,
        name=f"Inquirer {contact_id}",
        email=email,
        phone_digits=phone,
        source="other",
        pipeline_status="lead",
        consent=ContactConsent(contact_about_request=True, captured_at=NOW),
        created_at=NOW,
        updated_at=NOW,
    )


def _contact(contact_id: str, *, email: str | None) -> FamilyContact:
    return FamilyContact(
        contact_id=contact_id,
        academy_id=A,
        parent_id="p-9",
        name=f"Contact {contact_id}",
        email=email,
        created_by="u-1",
        created_at=NOW,
        updated_at=NOW,
    )


def _use_case(
    *,
    index: _Index | None = None,
    contacts: _Lookup | None = None,
    members: _Members | None = None,
    inquiries: _Lookup | None = None,
) -> FindPossibleDuplicates:
    return FindPossibleDuplicates(
        families=index or _Index([]),
        family_contacts=contacts or _Lookup([]),
        members=members or _Members({}),
        inquiries=inquiries or _Lookup([]),
    )


async def test_empty_probe_asks_nothing() -> None:
    index, contacts, inquiries, members = _Index([]), _Lookup([]), _Lookup([]), _Members({})
    use_case = _use_case(index=index, contacts=contacts, members=members, inquiries=inquiries)
    assert await use_case.execute(A, DuplicateCheckQuery(email=" ", phone="12")) == []
    assert index.calls == [] and contacts.calls == [] and inquiries.calls == []
    assert members.calls == []


async def test_one_answer_per_record_with_every_reason_and_both_phone_spellings() -> None:
    inquiries = _Lookup(
        [_inquiry("l-1", email="dup@example.test", phone="15550102030")],
    )
    use_case = _use_case(inquiries=inquiries)
    matches = await use_case.execute(
        A, DuplicateCheckQuery(email="Dup@Example.test", phone="555 010 2030")
    )
    assert [(m.kind, m.record_id, m.matched_on) for m in matches] == [
        ("inquiry", "l-1", ("email", "phone"))
    ]
    assert inquiries.calls == [
        ("email", "dup@example.test"),
        ("phone", "5550102030"),
        ("phone", "15550102030"),
    ]


async def test_contact_matches_rank_before_name_only_matches_and_answer_is_capped() -> None:
    index = _Index([_family(f"p-{n}", "Common Name") for n in range(4)])
    contacts = _Lookup([_contact(f"c-{n}", email="shared@example.test") for n in range(3)])
    use_case = _use_case(index=index, contacts=contacts)
    matches = await use_case.execute(
        A, DuplicateCheckQuery(email="shared@example.test", name="common name")
    )
    assert len(matches) == 5
    assert [m.kind for m in matches[:3]] == ["family_contact"] * 3
    assert all(m.matched_on == ("name",) for m in matches[3:])
    assert matches[0].link == "/admin/families/p-9"


async def test_a_member_who_is_already_a_family_is_reported_once() -> None:
    index = _Index([_family("u-1", "Testparent One", "one@example.test")])
    members = _Members(
        {
            (A, "one@example.test"): _Member("u-1", "Testparent One", "one@example.test", None),
            (A, "staff@example.test"): _Member("u-2", None, "staff@example.test", None),
        }
    )
    use_case = _use_case(index=index, members=members)
    parent = await use_case.execute(A, DuplicateCheckQuery(email="one@example.test"))
    assert [(m.kind, m.record_id) for m in parent] == [("family", "u-1")]
    staff = await use_case.execute(A, DuplicateCheckQuery(email="staff@example.test"))
    assert [(m.kind, m.display_name, m.link) for m in staff] == [
        ("user", "Unnamed user", "/admin/users/u-2")
    ]
    assert members.calls[-1] == (A, "staff@example.test")


async def test_a_failed_family_index_is_skipped_not_raised() -> None:
    inquiries = _Lookup([_inquiry("l-1", email="dup@example.test", phone=None)])
    use_case = _use_case(index=_Index([], fail=True), inquiries=inquiries)
    matches = await use_case.execute(A, DuplicateCheckQuery(email="dup@example.test"))
    assert [(m.kind, m.record_id) for m in matches] == [("inquiry", "l-1")]


async def test_linked_inquiry_opens_its_family() -> None:
    linked = _inquiry("l-2", email="linked@example.test", phone=None).model_copy(
        update={"linked_family_id": "fb/uid"}
    )
    use_case = _use_case(inquiries=_Lookup([linked]))
    matches = await use_case.execute(A, DuplicateCheckQuery(email="linked@example.test"))
    assert matches[0].link == "/admin/families/fb%2Fuid"
