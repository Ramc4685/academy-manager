"""Admin waiver template management use-case tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from backend.v2.contexts.onboarding.application.use_cases.admin_waiver_templates import (
    AdminWaiverTemplateRecord,
    AssignWaiverTemplateToRegistrationCommand,
    CreateDraftWaiverTemplateCommand,
    ManageAdminWaiverTemplates,
    PublishWaiverTemplateCommand,
)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


@dataclass
class FakeTemplateRepo:
    rows: dict[str, AdminWaiverTemplateRecord] = field(default_factory=dict)

    async def list_templates(self) -> list[AdminWaiverTemplateRecord]:
        return sorted(self.rows.values(), key=lambda row: row.updated_at, reverse=True)

    async def create_draft(self, template: AdminWaiverTemplateRecord) -> AdminWaiverTemplateRecord:
        self.rows[template.waiver_template_id] = template
        return template

    async def get_template(self, waiver_template_id: str) -> AdminWaiverTemplateRecord | None:
        return self.rows.get(waiver_template_id)

    async def publish_draft(
        self,
        *,
        waiver_template_id: str,
        version: str,
        content_hash: str,
        published_at: datetime,
    ) -> AdminWaiverTemplateRecord:
        current = self.rows[waiver_template_id]
        for row_id, row in list(self.rows.items()):
            if row.status == "active":
                self.rows[row_id] = row.model_copy(update={"status": "superseded"})
        published = current.model_copy(
            update={
                "version": version,
                "status": "active",
                "content_hash": content_hash,
                "effective_from": published_at,
                "published_at": published_at,
                "updated_at": published_at,
            }
        )
        self.rows[waiver_template_id] = published
        return published

    async def assign_to_registration(
        self, *, waiver_template_id: str, assigned_at: datetime
    ) -> AdminWaiverTemplateRecord:
        for row_id, row in list(self.rows.items()):
            if row.assigned_to_registration:
                self.rows[row_id] = row.model_copy(
                    update={"assigned_to_registration": False, "assigned_at": None}
                )
        current = self.rows[waiver_template_id]
        assigned = current.model_copy(
            update={
                "assigned_to_registration": True,
                "assigned_at": assigned_at,
                "updated_at": assigned_at,
            }
        )
        self.rows[waiver_template_id] = assigned
        return assigned


@pytest.mark.asyncio
async def test_admin_can_create_draft_and_list_template_metadata() -> None:
    repo = FakeTemplateRepo()
    use_case = ManageAdminWaiverTemplates(
        repo,
        id_factory=lambda: "wt-draft",
        clock=lambda: _dt("2026-05-24T15:00:00"),
    )

    draft = await use_case.create_draft(
        CreateDraftWaiverTemplateCommand(
            title="Summer waiver",
            body="Parent agrees to academy safety rules.",
        )
    )
    templates = await use_case.list_templates()

    assert draft.waiver_template_id == "wt-draft"
    assert draft.title == "Summer waiver"
    assert draft.body == "Parent agrees to academy safety rules."
    assert draft.status == "draft"
    assert draft.version is None
    assert draft.content_hash is None
    assert templates == [draft]


@pytest.mark.asyncio
async def test_admin_can_create_draft_from_content_alias() -> None:
    repo = FakeTemplateRepo()
    use_case = ManageAdminWaiverTemplates(
        repo,
        id_factory=lambda: "wt-content",
        clock=lambda: _dt("2026-05-24T15:00:00"),
    )

    draft = await use_case.create_draft(
        CreateDraftWaiverTemplateCommand(
            title="Alias waiver",
            content="Content field from API clients.",
        )
    )

    assert draft.body == "Content field from API clients."


@pytest.mark.asyncio
async def test_publish_draft_versions_hashes_and_supersedes_previous_active() -> None:
    repo = FakeTemplateRepo(
        rows={
            "wt-active": AdminWaiverTemplateRecord(
                waiver_template_id="wt-active",
                title="Current waiver",
                body="Published body must not be edited.",
                status="active",
                version="1",
                content_hash="old-hash",
                effective_from=_dt("2026-01-01T00:00:00"),
                published_at=_dt("2026-01-01T00:00:00"),
                updated_at=_dt("2026-01-01T00:00:00"),
            ),
            "wt-draft": AdminWaiverTemplateRecord(
                waiver_template_id="wt-draft",
                title="New waiver",
                body="New immutable snapshot.",
                status="draft",
                version=None,
                content_hash=None,
                effective_from=None,
                published_at=None,
                updated_at=_dt("2026-05-01T00:00:00"),
            ),
        }
    )
    use_case = ManageAdminWaiverTemplates(
        repo,
        clock=lambda: _dt("2026-05-24T15:00:00"),
    )

    published = await use_case.publish(PublishWaiverTemplateCommand(waiver_template_id="wt-draft"))

    assert published.status == "active"
    assert published.version == "2"
    assert published.content_hash is not None
    assert published.effective_from == _dt("2026-05-24T15:00:00")
    assert repo.rows["wt-active"].status == "superseded"
    assert repo.rows["wt-active"].body == "Published body must not be edited."


@pytest.mark.asyncio
async def test_publish_rejects_direct_published_mutation() -> None:
    repo = FakeTemplateRepo(
        rows={
            "wt-active": AdminWaiverTemplateRecord(
                waiver_template_id="wt-active",
                title="Current waiver",
                body="Published body.",
                status="active",
                version="1",
                content_hash="old-hash",
                effective_from=_dt("2026-01-01T00:00:00"),
                published_at=_dt("2026-01-01T00:00:00"),
                updated_at=_dt("2026-01-01T00:00:00"),
            )
        }
    )
    use_case = ManageAdminWaiverTemplates(repo)

    with pytest.raises(ValueError, match="Only draft waiver templates can be published"):
        await use_case.publish(PublishWaiverTemplateCommand(waiver_template_id="wt-active"))


@pytest.mark.asyncio
async def test_admin_can_assign_active_template_to_registration_flow() -> None:
    repo = FakeTemplateRepo(
        rows={
            "wt-active": AdminWaiverTemplateRecord(
                waiver_template_id="wt-active",
                title="Current waiver",
                body="Published body.",
                status="active",
                version="1",
                content_hash="hash",
                effective_from=_dt("2026-01-01T00:00:00"),
                published_at=_dt("2026-01-01T00:00:00"),
                updated_at=_dt("2026-01-01T00:00:00"),
            )
        }
    )
    use_case = ManageAdminWaiverTemplates(
        repo,
        clock=lambda: _dt("2026-05-24T15:00:00"),
    )

    assigned = await use_case.assign_to_registration(
        AssignWaiverTemplateToRegistrationCommand(waiver_template_id="wt-active")
    )

    assert assigned.assigned_to_registration is True
    assert assigned.assigned_at == _dt("2026-05-24T15:00:00")


@pytest.mark.asyncio
async def test_registration_assignment_rejects_draft_template() -> None:
    repo = FakeTemplateRepo(
        rows={
            "wt-draft": AdminWaiverTemplateRecord(
                waiver_template_id="wt-draft",
                title="Draft waiver",
                body="Draft body.",
                status="draft",
                updated_at=_dt("2026-05-01T00:00:00"),
            )
        }
    )
    use_case = ManageAdminWaiverTemplates(repo)

    with pytest.raises(ValueError, match="Only active waiver templates can be assigned"):
        await use_case.assign_to_registration(
            AssignWaiverTemplateToRegistrationCommand(waiver_template_id="wt-draft")
        )
