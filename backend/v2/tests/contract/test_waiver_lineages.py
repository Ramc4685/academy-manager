"""Several waivers live at once (Settings overhaul Phase 6, PR 23).

Every waiver is a lineage: all of its versions share a ``lineage_key``.
Publishing a version supersedes only the live rows of the SAME lineage. A row
without a key (everything that predates this change) is the one legacy
lineage, because those templates used to replace each other.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.onboarding.application.use_cases.admin_waiver_templates import (
    AssignWaiverCommand,
    CreateDraftWaiverTemplateCommand,
    ManageAdminWaiverTemplates,
    ProgramRef,
    PublishWaiverTemplateCommand,
)
from backend.v2.contexts.onboarding.domain.waiver_assignment import WaiverAssignment
from backend.v2.contexts.onboarding.infrastructure.mongo_parent_waiver_repo import (
    MongoParentWaiverRepository,
)
from backend.v2.contexts.onboarding.infrastructure.mongo_registration_waiver_repo import (
    MongoRegistrationWaiverRepository,
)
from backend.v2.contexts.onboarding.infrastructure.mongo_waiver_template_repo import (
    MongoWaiverTemplateRepository,
)

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


class _Programs:
    async def list_programs(self) -> list[ProgramRef]:
        return [
            ProgramRef(program_id="prog-juniors", name="Juniors"),
            ProgramRef(program_id="prog-adults", name="Adults"),
        ]

    async def list_archived_programs(self) -> list[ProgramRef]:
        return []


class _Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        self.now += timedelta(minutes=1)
        return self.now


def _manager(db) -> tuple[ManageAdminWaiverTemplates, MongoWaiverTemplateRepository]:
    repo = MongoWaiverTemplateRepository(db)
    ids = iter(f"wt-{n}" for n in range(1, 50))
    return (
        ManageAdminWaiverTemplates(
            repo, programs=_Programs(), id_factory=lambda: next(ids), clock=_Clock()
        ),
        repo,
    )


async def _publish_new_waiver(manager, title: str) -> str:
    draft = await manager.create_draft(CreateDraftWaiverTemplateCommand(title=title, body="body"))
    published = await manager.publish(
        PublishWaiverTemplateCommand(waiver_template_id=draft.waiver_template_id)
    )
    return published.waiver_template_id


@pytest.mark.asyncio
async def test_two_waivers_stay_live_together(db, acad) -> None:
    manager, _repo = _manager(db)

    liability = await _publish_new_waiver(manager, "Liability")
    photo = await _publish_new_waiver(manager, "Photo consent")

    rows = {row.waiver_template_id: row for row in await manager.list_templates()}
    assert rows[liability].status == "active"
    assert rows[photo].status == "active"
    assert rows[liability].lineage != rows[photo].lineage
    # Each waiver numbers its own versions.
    assert rows[liability].version == "1"
    assert rows[photo].version == "1"


@pytest.mark.asyncio
async def test_publishing_a_new_version_supersedes_only_its_own_lineage(db, acad) -> None:
    manager, _repo = _manager(db)
    liability_v1 = await _publish_new_waiver(manager, "Liability")
    photo_v1 = await _publish_new_waiver(manager, "Photo consent")

    draft = await manager.create_draft(
        CreateDraftWaiverTemplateCommand(
            title="Liability", body="new wording", based_on_waiver_template_id=liability_v1
        )
    )
    v2 = await manager.publish(
        PublishWaiverTemplateCommand(waiver_template_id=draft.waiver_template_id)
    )

    rows = {row.waiver_template_id: row for row in await manager.list_templates()}
    assert v2.version == "2"
    assert v2.lineage == rows[liability_v1].lineage
    assert rows[liability_v1].status == "superseded"
    assert rows[v2.waiver_template_id].status == "active"
    assert rows[photo_v1].status == "active"
    assert rows[photo_v1].version == "1"


@pytest.mark.asyncio
async def test_new_version_inherits_assignment_and_registration_flag(db, acad) -> None:
    manager, repo = _manager(db)
    photo_v1 = await _publish_new_waiver(manager, "Photo consent")
    await manager.assign(
        AssignWaiverCommand(
            waiver_template_id=photo_v1,
            required=True,
            scope="programs",
            program_ids=["prog-juniors"],
        )
    )
    liability_v1 = await _publish_new_waiver(manager, "Liability")
    await manager.assign(AssignWaiverCommand(waiver_template_id=liability_v1, required=True))

    draft = await manager.create_draft(
        CreateDraftWaiverTemplateCommand(
            title="Photo consent", body="v2", based_on_waiver_template_id=photo_v1
        )
    )
    photo_v2 = await manager.publish(
        PublishWaiverTemplateCommand(waiver_template_id=draft.waiver_template_id)
    )

    assert photo_v2.required is True
    assert photo_v2.scope == "programs"
    assert photo_v2.program_ids == ["prog-juniors"]
    assert photo_v2.assigned_to_registration is False
    required = {row.waiver_template_id: row for row in await repo.list_required_templates()}
    assert set(required) == {liability_v1, photo_v2.waiver_template_id}
    assert required[liability_v1].assigned_to_registration is True


@pytest.mark.asyncio
async def test_rows_without_a_lineage_key_are_one_legacy_lineage(db, acad) -> None:
    """Pre-existing templates replaced each other, so they are one waiver."""
    await db["waiver_templates"].insert_many(
        [
            {
                "academy_id": acad,
                "waiver_template_id": "wt-old",
                "name": "BLNO waiver",
                "body": "old",
                "status": "active",
                "version": "1",
                "content_hash": "h1",
                "effective_from": T0,
                "updated_at": T0,
                "assigned_to_registration": True,
                "assigned_at": T0,
            },
            {
                "academy_id": acad,
                "waiver_template_id": "wt-draft",
                "name": "BLNO waiver",
                "body": "new",
                "status": "draft",
                "updated_at": T0,
            },
        ]
    )
    manager, repo = _manager(db)

    old = await repo.get_template("wt-old")
    assert old is not None
    assert old.lineage == "legacy"
    # Read at read time as required for all families: BLNO is unchanged.
    assert old.required is True
    assert old.scope == "all"

    published = await manager.publish(PublishWaiverTemplateCommand(waiver_template_id="wt-draft"))

    assert published.version == "2"
    assert published.lineage == "legacy"
    assert published.assigned_to_registration is True
    superseded = await repo.get_template("wt-old")
    assert superseded is not None and superseded.status == "superseded"
    stored = await db["waiver_templates"].find_one({"waiver_template_id": "wt-draft"})
    assert stored["lineage_key"] == "legacy"
    registration = await repo.get_registration_template()
    assert registration is not None and registration.waiver_template_id == "wt-draft"


@pytest.mark.asyncio
async def test_a_new_waiver_does_not_replace_the_legacy_one(db, acad) -> None:
    await db["waiver_templates"].insert_one(
        {
            "academy_id": acad,
            "waiver_template_id": "wt-old",
            "name": "BLNO waiver",
            "body": "old",
            "status": "published",
            "version": "3",
            "content_hash": "h3",
            "effective_from": T0,
            "updated_at": T0,
            "assigned_to_registration": True,
            "assigned_at": T0,
        }
    )
    manager, repo = _manager(db)

    photo = await _publish_new_waiver(manager, "Photo consent")

    old = await repo.get_template("wt-old")
    assert old is not None and old.status == "active"
    assert old.assigned_to_registration is True
    assert photo != "wt-old"


@pytest.mark.asyncio
async def test_lineages_are_tenant_scoped(db, acad, other_acad) -> None:
    # `acad` set first, then `other_acad` replaced the context var; publish in
    # the second tenant must not touch the first tenant's live waiver.
    await db["waiver_templates"].insert_many(
        [
            {
                "academy_id": "test-academy",
                "waiver_template_id": "wt-a",
                "name": "A",
                "body": "a",
                "status": "active",
                "version": "1",
                "content_hash": "ha",
                "effective_from": T0,
                "updated_at": T0,
                "lineage_key": "legacy",
            },
            {
                "academy_id": "other-academy",
                "waiver_template_id": "wt-b-draft",
                "name": "B",
                "body": "b",
                "status": "draft",
                "updated_at": T0,
                "lineage_key": "legacy",
            },
        ]
    )
    repo = MongoWaiverTemplateRepository(db)

    await repo.publish_draft(
        waiver_template_id="wt-b-draft", version="1", content_hash="hb", published_at=T0
    )

    untouched = await db["waiver_templates"].find_one({"waiver_template_id": "wt-a"})
    assert untouched["status"] == "active"


@pytest.mark.asyncio
async def test_assign_validates_scope_and_programs(db, acad) -> None:
    manager, _repo = _manager(db)
    live = await _publish_new_waiver(manager, "Photo consent")
    draft = await manager.create_draft(CreateDraftWaiverTemplateCommand(title="Draft", body="b"))

    with pytest.raises(ValueError, match="Choose at least one program"):
        await manager.assign(
            AssignWaiverCommand(waiver_template_id=live, required=True, scope="programs")
        )
    with pytest.raises(ValueError, match="Unknown program"):
        await manager.assign(
            AssignWaiverCommand(
                waiver_template_id=live,
                required=True,
                scope="programs",
                program_ids=["prog-nope"],
            )
        )
    with pytest.raises(ValueError, match="Only active"):
        await manager.assign(
            AssignWaiverCommand(waiver_template_id=draft.waiver_template_id, required=True)
        )

    none_required = await manager.assign(
        AssignWaiverCommand(waiver_template_id=live, required=False)
    )
    assert none_required.required is False
    assert none_required.assigned_to_registration is False


@pytest.mark.asyncio
async def test_registration_waivers_are_all_family_plus_the_classes_program(db, acad) -> None:
    manager, _repo = _manager(db)
    liability = await _publish_new_waiver(manager, "Liability")
    photo = await _publish_new_waiver(manager, "Photo consent")
    await _publish_new_waiver(manager, "Unassigned")
    await manager.assign(AssignWaiverCommand(waiver_template_id=liability, required=True))
    await manager.assign(
        AssignWaiverCommand(
            waiver_template_id=photo, required=True, scope="programs", program_ids=["prog-juniors"]
        )
    )
    await db["sessions"].insert_many(
        [
            {"academy_id": acad, "session_id": "s-juniors", "program_id": "prog-juniors"},
            {"academy_id": acad, "session_id": "s-adults", "program_id": "prog-adults"},
            {"academy_id": acad, "session_id": "s-none"},
        ]
    )
    repo = MongoRegistrationWaiverRepository(db)

    juniors = await repo.list_required("s-juniors")
    adults = await repo.list_required("s-adults")
    ungrouped = await repo.list_required("s-none")
    before_class = await repo.list_required(None)

    assert [w.waiver_id for w in juniors] == [liability, photo]
    assert [w.waiver_id for w in adults] == [liability]
    assert [w.waiver_id for w in ungrouped] == [liability]
    assert [w.waiver_id for w in before_class] == [liability]
    assert await repo.has_program_scoped_waivers() is True
    assert juniors[0].title == "Liability"


@pytest.mark.asyncio
async def test_single_all_families_waiver_reads_exactly_as_get_active(db, acad) -> None:
    await db["waiver_templates"].insert_one(
        {
            "academy_id": acad,
            "waiver_template_id": "wt-blno",
            "name": "BLNO waiver",
            "body": "text",
            "status": "active",
            "version": "2026.1",
            "content_hash": "h",
            "effective_from": T0,
            "assigned_to_registration": True,
            "assigned_at": T0,
            "updated_at": T0,
        }
    )
    repo = MongoRegistrationWaiverRepository(db)

    listed = await repo.list_required("anything")
    active = await repo.get_active()

    assert active is not None
    assert [w.waiver_id for w in listed] == [active.waiver_id]
    assert listed[0].content_hash == active.content_hash
    assert await repo.has_program_scoped_waivers() is False


@pytest.mark.asyncio
async def test_no_assignment_falls_back_to_the_legacy_published_row(db, acad) -> None:
    await db["waiver_templates"].insert_one(
        {
            "academy_id": acad,
            "waiver_template_id": "wt-legacy",
            "name": "Legacy",
            "body": "text",
            "status": "published",
            "version": "1",
            "content_hash": "h",
            "effective_from": T0,
            "published_at": T0,
            "updated_at": T0,
        }
    )
    repo = MongoRegistrationWaiverRepository(db)

    listed = await repo.list_required(None)
    active = await repo.get_active()

    assert active is not None
    assert [w.waiver_id for w in listed] == ["wt-legacy"]


@pytest.mark.asyncio
async def test_signatures_are_filed_per_lineage(db, acad) -> None:
    await db["waiver_templates"].insert_many(
        [
            {
                "academy_id": acad,
                "waiver_template_id": "wt-l1",
                "name": "Liability",
                "version": "1",
                "content_hash": "hl1",
                "status": "superseded",
                "lineage_key": "legacy",
            },
            {
                "academy_id": acad,
                "waiver_template_id": "wt-l2",
                "name": "Liability",
                "version": "2",
                "content_hash": "hl2",
                "status": "active",
                "lineage_key": "legacy",
            },
            {
                "academy_id": acad,
                "waiver_template_id": "wt-p1",
                "name": "Photo",
                "version": "1",
                "content_hash": "hp1",
                "status": "active",
                "lineage_key": "wl-photo",
            },
        ]
    )
    await db["waiver_signatures"].insert_many(
        [
            {
                "academy_id": acad,
                "waiver_signature_id": "ws-1",
                "waiver_template_id": "wt-l1",
                "student_id": "st-1",
                "parent_user_id": "p-1",
                "content_hash": "hl1",
                "signed_at": T0,
            },
            {
                "academy_id": acad,
                "waiver_signature_id": "ws-2",
                "waiver_template_id": "wt-p1",
                "student_id": "st-1",
                "parent_user_id": "p-1",
                "content_hash": "hp1",
                "signed_at": T0 + timedelta(days=1),
            },
        ]
    )
    repo = MongoParentWaiverRepository(db)

    signatures = await repo.signatures_for_students(["st-1", "st-2"])

    assert set(signatures) == {("st-1", "legacy"), ("st-1", "wl-photo")}
    liability = signatures[("st-1", "legacy")]
    assert liability.waiver_template_id == "wt-l1"
    assert liability.signed_version == "1"
    assert liability.waiver_signature_id == "ws-1"
    assert signatures[("st-1", "wl-photo")].waiver_template_id == "wt-p1"


def test_assignment_defaults_and_scope_rules() -> None:
    assert WaiverAssignment().applies_to(["prog-juniors"]) is False
    everyone = WaiverAssignment(required=True)
    assert everyone.applies_to([]) is True
    programs = WaiverAssignment(required=True, scope="programs", program_ids=("prog-juniors",))
    assert programs.applies_to([None, "prog-juniors"]) is True
    assert programs.applies_to(["prog-adults"]) is False
    assert programs.applies_to([]) is False


@pytest.mark.asyncio
async def test_failed_publish_leaves_the_live_waiver_untouched(db, acad) -> None:
    """A version collision (e.g. the old (academy, version) index, before 0211)
    raises a conflict and does NOT supersede the live waiver first."""
    from backend.v2.contexts.onboarding.application.use_cases.admin_waiver_templates import (
        WaiverVersionConflict,
    )

    manager, _repo = _manager(db)
    liability = await _publish_new_waiver(manager, "Liability")
    await db["waiver_templates"].create_index(
        [("academy_id", 1), ("version", 1)],
        unique=True,
        name="old_academy_version_unique_for_test",
    )
    draft = await manager.create_draft(CreateDraftWaiverTemplateCommand(title="Photo", body="b"))

    with pytest.raises(WaiverVersionConflict):
        await manager.publish(
            PublishWaiverTemplateCommand(waiver_template_id=draft.waiver_template_id)
        )

    rows = {row.waiver_template_id: row for row in await manager.list_templates()}
    assert rows[liability].status == "active"
    assert rows[draft.waiver_template_id].status == "draft"
