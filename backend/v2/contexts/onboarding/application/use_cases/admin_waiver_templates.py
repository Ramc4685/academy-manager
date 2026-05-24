"""Admin waiver template management use cases."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal, Protocol

from pydantic import BaseModel

from backend.v2.shared.ids import new_ulid

AdminManagedWaiverTemplateStatus = Literal["draft", "active", "superseded", "retired"]


class AdminWaiverTemplateRecord(BaseModel):
    model_config = {"frozen": True}

    waiver_template_id: str
    title: str
    body: str
    status: AdminManagedWaiverTemplateStatus
    version: str | None = None
    content_hash: str | None = None
    effective_from: datetime | None = None
    published_at: datetime | None = None
    assigned_to_registration: bool = False
    assigned_at: datetime | None = None
    updated_at: datetime


class CreateDraftWaiverTemplateCommand(BaseModel):
    title: str
    body: str | None = None
    content: str | None = None


class PublishWaiverTemplateCommand(BaseModel):
    waiver_template_id: str


class AssignWaiverTemplateToRegistrationCommand(BaseModel):
    waiver_template_id: str


class AdminWaiverTemplateManagementRepo(Protocol):
    async def list_templates(self) -> list[AdminWaiverTemplateRecord]: ...

    async def create_draft(
        self, template: AdminWaiverTemplateRecord
    ) -> AdminWaiverTemplateRecord: ...

    async def get_template(self, waiver_template_id: str) -> AdminWaiverTemplateRecord | None: ...

    async def publish_draft(
        self,
        *,
        waiver_template_id: str,
        version: str,
        content_hash: str,
        published_at: datetime,
    ) -> AdminWaiverTemplateRecord: ...

    async def assign_to_registration(
        self,
        *,
        waiver_template_id: str,
        assigned_at: datetime,
    ) -> AdminWaiverTemplateRecord: ...


class WaiverTemplateNotFound(ValueError):
    pass


class WaiverTemplateNotDraft(ValueError):
    pass


class ManageAdminWaiverTemplates:
    def __init__(
        self,
        templates: AdminWaiverTemplateManagementRepo,
        *,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._templates = templates
        self._id_factory = id_factory or (lambda: f"wt_{new_ulid()}")
        self._clock = clock or (lambda: datetime.now(UTC))

    async def list_templates(self) -> list[AdminWaiverTemplateRecord]:
        return await self._templates.list_templates()

    async def create_draft(
        self, command: CreateDraftWaiverTemplateCommand
    ) -> AdminWaiverTemplateRecord:
        title = command.title.strip()
        body = (command.body if command.body is not None else command.content or "").strip()
        if not title:
            raise ValueError("Waiver template title is required")
        if not body:
            raise ValueError("Waiver template body is required")

        now = self._clock()
        template = AdminWaiverTemplateRecord(
            waiver_template_id=self._id_factory(),
            title=title,
            body=body,
            status="draft",
            updated_at=now,
        )
        return await self._templates.create_draft(template)

    async def publish(self, command: PublishWaiverTemplateCommand) -> AdminWaiverTemplateRecord:
        template = await self._templates.get_template(command.waiver_template_id)
        if template is None:
            raise WaiverTemplateNotFound("Waiver template not found")
        if template.status != "draft":
            raise WaiverTemplateNotDraft("Only draft waiver templates can be published")

        existing = await self._templates.list_templates()
        version = self._next_version(existing)
        content_hash = sha256(template.body.encode("utf-8")).hexdigest()
        return await self._templates.publish_draft(
            waiver_template_id=template.waiver_template_id,
            version=version,
            content_hash=content_hash,
            published_at=self._clock(),
        )

    async def assign_to_registration(
        self, command: AssignWaiverTemplateToRegistrationCommand
    ) -> AdminWaiverTemplateRecord:
        template = await self._templates.get_template(command.waiver_template_id)
        if template is None:
            raise WaiverTemplateNotFound("Waiver template not found")
        if template.status != "active":
            raise ValueError("Only active waiver templates can be assigned to registration")
        return await self._templates.assign_to_registration(
            waiver_template_id=template.waiver_template_id,
            assigned_at=self._clock(),
        )

    @staticmethod
    def _next_version(templates: list[AdminWaiverTemplateRecord]) -> str:
        published = [template for template in templates if template.status != "draft"]
        numeric_versions: list[int] = []
        for template in published:
            if template.version and template.version.isdigit():
                numeric_versions.append(int(template.version))
        if numeric_versions:
            return str(max(numeric_versions) + 1)
        return str(len(published) + 1)
