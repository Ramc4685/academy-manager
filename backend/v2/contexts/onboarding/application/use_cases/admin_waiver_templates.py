"""Admin waiver template management use cases."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from backend.v2.contexts.onboarding.domain.waiver_assignment import (
    LEGACY_LINEAGE_KEY,
    WaiverAssignment,
    WaiverScope,
)
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
    # Every version of one waiver shares a lineage key. ``None`` reads as the
    # legacy lineage (every template that predates the key).
    lineage_key: str | None = None
    # Who must sign it (decision 8). The stored flag ``assigned_to_registration``
    # alone reads as "required for all families".
    required: bool = False
    scope: WaiverScope = "all"
    program_ids: list[str] = Field(default_factory=list)

    @property
    def lineage(self) -> str:
        return self.lineage_key or LEGACY_LINEAGE_KEY

    @property
    def assignment(self) -> WaiverAssignment:
        return WaiverAssignment(
            required=self.required,
            scope=self.scope,
            program_ids=tuple(self.program_ids),
        )


class ProgramRef(BaseModel):
    model_config = {"frozen": True}

    program_id: str
    name: str


class ProgramDirectory(Protocol):
    """The academy's live programs (class groups), owned by Enrollment."""

    async def list_programs(self) -> list[ProgramRef]: ...


class CreateDraftWaiverTemplateCommand(BaseModel):
    title: str
    body: str | None = None
    content: str | None = None
    # Set to draft a new VERSION of an existing waiver; left out, the draft is
    # a new waiver of its own (its own lineage, so publishing it leaves every
    # other live waiver alone).
    based_on_waiver_template_id: str | None = None


class AssignWaiverCommand(BaseModel):
    waiver_template_id: str
    required: bool
    scope: WaiverScope = "all"
    program_ids: list[str] = Field(default_factory=list)


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

    async def set_assignment(
        self,
        *,
        waiver_template_id: str,
        assignment: WaiverAssignment,
        assigned_at: datetime,
    ) -> AdminWaiverTemplateRecord: ...


class WaiverTemplateNotFound(ValueError):
    pass


class WaiverTemplateNotDraft(ValueError):
    pass


class WaiverVersionConflict(ValueError):
    """The version being published is already taken, or the draft was published meanwhile."""


class ManageAdminWaiverTemplates:
    def __init__(
        self,
        templates: AdminWaiverTemplateManagementRepo,
        *,
        programs: ProgramDirectory | None = None,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._templates = templates
        self._programs = programs
        self._id_factory = id_factory or (lambda: f"wt_{new_ulid()}")
        self._clock = clock or (lambda: datetime.now(UTC))

    async def list_templates(self) -> list[AdminWaiverTemplateRecord]:
        return await self._templates.list_templates()

    async def list_programs(self) -> list[ProgramRef]:
        if self._programs is None:
            return []
        return await self._programs.list_programs()

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
        waiver_template_id = self._id_factory()
        lineage_key = waiver_template_id
        if command.based_on_waiver_template_id:
            source = await self._templates.get_template(command.based_on_waiver_template_id)
            if source is None:
                raise WaiverTemplateNotFound("Waiver template not found")
            lineage_key = source.lineage
        template = AdminWaiverTemplateRecord(
            waiver_template_id=waiver_template_id,
            title=title,
            body=body,
            status="draft",
            updated_at=now,
            lineage_key=lineage_key,
        )
        return await self._templates.create_draft(template)

    async def publish(self, command: PublishWaiverTemplateCommand) -> AdminWaiverTemplateRecord:
        template = await self._templates.get_template(command.waiver_template_id)
        if template is None:
            raise WaiverTemplateNotFound("Waiver template not found")
        if template.status != "draft":
            raise WaiverTemplateNotDraft("Only draft waiver templates can be published")

        existing = await self._templates.list_templates()
        # Versions count per waiver: publishing "Photo consent" must not skip a
        # number because "Liability" was republished in between.
        version = self._next_version([row for row in existing if row.lineage == template.lineage])
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

    async def assign(self, command: AssignWaiverCommand) -> AdminWaiverTemplateRecord:
        template = await self._templates.get_template(command.waiver_template_id)
        if template is None:
            raise WaiverTemplateNotFound("Waiver template not found")
        if template.status != "active":
            raise ValueError("Only active waiver templates can be assigned")
        program_ids = list(dict.fromkeys(pid.strip() for pid in command.program_ids if pid.strip()))
        if not command.required:
            assignment = WaiverAssignment(required=False)
        elif command.scope == "all":
            assignment = WaiverAssignment(required=True, scope="all")
        else:
            if not program_ids:
                raise ValueError("Choose at least one program")
            known = {program.program_id for program in await self.list_programs()}
            unknown = [pid for pid in program_ids if pid not in known]
            if unknown:
                raise ValueError("Unknown program")
            assignment = WaiverAssignment(
                required=True, scope="programs", program_ids=tuple(program_ids)
            )
        return await self._templates.set_assignment(
            waiver_template_id=template.waiver_template_id,
            assignment=assignment,
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
