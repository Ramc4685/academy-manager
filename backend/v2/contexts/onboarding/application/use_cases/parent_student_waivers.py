"""Parent-facing required waiver read/sign use cases."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from backend.v2.contexts.onboarding.application.use_cases.admin_waiver_templates import (
    AdminWaiverTemplateRecord,
)
from backend.v2.contexts.onboarding.domain.errors import (
    WaiverDateOfBirthMissing,
    WaiverSignatureIncomplete,
    WaiverSignatureNotFound,
    WaiverStudentNotFound,
)
from backend.v2.contexts.onboarding.domain.models import (
    ESIGN_CONSENT_TEXT,
    WaiverSignature,
    clean_signer_name,
)
from backend.v2.contexts.onboarding.domain.waiver_assignment import LEGACY_LINEAGE_KEY
from backend.v2.contexts.onboarding.domain.waiver_sections import (
    SigningPath,
    has_age_paths,
    missing_initials,
    parse_sections,
    signing_path_for,
)
from backend.v2.shared.ids import new_ulid

__all__ = ["ESIGN_CONSENT_TEXT"]  # re-exported for the interface layer (ADR-0005 rule 4)

logger = logging.getLogger(__name__)

ParentWaiverStatus = Literal["signed", "pending", "outdated", "not_required"]


class ParentWaiverStudent(BaseModel):
    model_config = {"frozen": True}

    student_id: str
    student_name: str
    date_of_birth: str | None = None


class ParentWaiverSignature(BaseModel):
    model_config = {"frozen": True}

    student_id: str
    waiver_template_id: str | None = None
    waiver_version: str | None = None
    content_hash: str | None = None
    # Who signed. A child whose guardian changed keeps the old parent's
    # signature row, and keying only by student made the new parent's page read
    # "signed" off a stranger's consent (#785). ``None`` means the stored row
    # predates the field: treated as "signer unknown", never as a mismatch.
    parent_user_id: str | None = None
    # Stamped by the admin change-parent write. Belt and braces for rows whose
    # ``parent_user_id`` is unknown but which we know were inherited.
    outdated_for_parent: bool = False
    signed_at: datetime | None = None
    # Which waiver (across versions) the signature is for; ``None`` reads as the
    # legacy lineage, and so does a signature whose template has no key.
    lineage_key: str | None = None
    waiver_signature_id: str | None = None
    # The version of the template the signature pins to (for staff views).
    signed_version: str | None = None
    signing_path: SigningPath | None = None

    @property
    def lineage(self) -> str:
        return self.lineage_key or LEGACY_LINEAGE_KEY


class ParentWaiverStudentStatus(BaseModel):
    model_config = {"frozen": True}

    student_id: str
    student_name: str
    status: ParentWaiverStatus
    signed_at: datetime | None = None
    waiver_version: str | None = None
    # The signature behind a "signed" / "outdated" status, for the signed copy.
    waiver_signature_id: str | None = None
    # Which sections apply, when the waiver has adult and minor sections.
    signing_path: SigningPath | None = None
    date_of_birth_missing: bool = False


class ParentWaiverItem(BaseModel):
    """One waiver and the children who must sign it."""

    model_config = {"frozen": True}

    waiver_template_id: str
    title: str | None = None
    version: str | None = None
    body: str | None = None
    students: list[ParentWaiverStudentStatus]


class ParentWaiverRequirement(BaseModel):
    model_config = {"frozen": True}

    required: bool
    # The first waiver, flat: a single-waiver academy (every academy today)
    # reads exactly as it always has.
    waiver_template_id: str | None = None
    title: str | None = None
    version: str | None = None
    body: str | None = None
    students: list[ParentWaiverStudentStatus]
    waivers: list[ParentWaiverItem] = []


class ParentSignedWaiverCopy(BaseModel):
    """Everything a signed copy shows: the exact text and the audit trail."""

    model_config = {"frozen": True}

    waiver_signature_id: str
    student_id: str
    student_name: str
    parent_user_id: str | None = None
    title: str | None = None
    version: str | None = None
    body: str
    content_hash: str | None = None
    signed_at: datetime | None = None
    signer_name: str
    signer_email: str | None = None
    consent_text: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    initials: dict[str, str] = {}
    signing_path: SigningPath | None = None


class ParentWaiverRepository(Protocol):
    async def list_required_templates(self) -> list[AdminWaiverTemplateRecord]: ...
    async def list_active_students_for_parent(
        self, parent_id: str
    ) -> list[ParentWaiverStudent]: ...
    async def program_ids_for_students(self, student_ids: list[str]) -> dict[str, set[str]]: ...
    async def signatures_for_students(
        self, student_ids: list[str]
    ) -> dict[tuple[str, str], ParentWaiverSignature]:
        """Latest signature per (student id, lineage key)."""
        ...

    async def save_signature(self, signature: WaiverSignature) -> None: ...

    async def signed_copy(self, waiver_signature_id: str) -> ParentSignedWaiverCopy | None:
        """The text as stored when signed (falling back to the template)."""
        ...


class _RequiredSet(BaseModel):
    """The live waivers that apply to this parent's children, and to whom."""

    model_config = {"frozen": True}

    students: list[ParentWaiverStudent]
    # (template, students it applies to), in display order.
    waivers: list[tuple[AdminWaiverTemplateRecord, list[ParentWaiverStudent]]]


async def _required_set(waivers: ParentWaiverRepository, parent_id: str) -> _RequiredSet:
    templates = await waivers.list_required_templates()
    students = await waivers.list_active_students_for_parent(parent_id)
    if not templates:
        return _RequiredSet(students=students, waivers=[])
    if not students:
        # No live-enrolled child: the page still shows the waiver everyone
        # signs (as it did with one registration waiver), with nobody to sign.
        everyone = [t for t in templates if t.assignment.for_all_families]
        return _RequiredSet(students=students, waivers=[(t, []) for t in everyone])
    programs = await waivers.program_ids_for_students([s.student_id for s in students])
    applicable: list[tuple[AdminWaiverTemplateRecord, list[ParentWaiverStudent]]] = []
    for template in templates:
        covered = [
            student
            for student in students
            if template.assignment.applies_to(programs.get(student.student_id, set()))
        ]
        if covered:
            applicable.append((template, covered))
    # All-family waivers first: the primary one is the same waiver a
    # single-waiver academy has always shown.
    applicable.sort(key=lambda pair: 0 if pair[0].assignment.for_all_families else 1)
    return _RequiredSet(students=students, waivers=applicable)


def _not_required(students: list[ParentWaiverStudent]) -> ParentWaiverRequirement:
    return ParentWaiverRequirement(
        required=False,
        students=[
            ParentWaiverStudentStatus(
                student_id=student.student_id,
                student_name=student.student_name,
                status="not_required",
            )
            for student in students
        ],
    )


class GetParentWaiverRequirement:
    def __init__(
        self,
        *,
        waivers: ParentWaiverRepository,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._waivers = waivers
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, *, parent_id: str) -> ParentWaiverRequirement:
        required = await _required_set(self._waivers, parent_id)
        if not required.waivers:
            return _not_required(required.students)
        signatures = await self._waivers.signatures_for_students(
            [student.student_id for student in required.students]
        )
        return _requirement_view(required, signatures, parent_id=parent_id, now=self._clock())


class WaiverSignedNotifier(Protocol):
    """Emails the signer a receipt for the signatures one signing act created.

    Onboarding must not import communications; the adapter lives in
    ``composition/waiver_receipt_email.py``. Best-effort: the signatures are
    already durable when this runs.
    """

    async def waivers_signed(
        self, *, parent_user_id: str, signer_email: str, waiver_signature_ids: list[str]
    ) -> None: ...


class AcceptParentWaiver:
    def __init__(
        self,
        *,
        waivers: ParentWaiverRepository,
        academy_id: Callable[[], str],
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
        notifier: WaiverSignedNotifier | None = None,
    ) -> None:
        self._waivers = waivers
        self._academy_id = academy_id
        self._notifier = notifier
        self._id_factory = id_factory or (lambda: f"ws_{new_ulid()}")
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(
        self,
        *,
        parent_id: str,
        signer_name: str | None,
        signer_email: str,
        ip_address: str | None,
        user_agent: str | None,
        consent: bool,
        student_ids: list[str] | None = None,
        initials: dict[str, dict[str, str]] | None = None,
    ) -> ParentWaiverRequirement:
        # A signature needs a deliberate act: a typed full name and the ticked
        # consent box. The old email fallback recorded no intent at all.
        name = clean_signer_name(signer_name)
        if name is None or not consent:
            raise WaiverSignatureIncomplete(
                "Type your full name and tick the consent box to sign.",
                missing_name=name is None,
                missing_consent=not consent,
            )
        required = await _required_set(self._waivers, parent_id)
        if not required.waivers:
            return _not_required(required.students)
        chosen: set[str] | None = None
        if student_ids is not None:
            chosen = set(student_ids)
            own = {student.student_id for student in required.students}
            if not chosen or not chosen <= own:
                raise WaiverStudentNotFound("Child not found")

        signatures = await self._waivers.signatures_for_students(
            [student.student_id for student in required.students]
        )
        now = self._clock()
        # Plan every signature first: a missing date of birth or initials
        # refuses the whole act, never half of it.
        planned: list[
            tuple[AdminWaiverTemplateRecord, ParentWaiverStudent, SigningPath | None]
        ] = []
        no_birth_date: list[str] = []
        for template, covered in required.waivers:
            sections = parse_sections(template.body)
            for student in covered:
                if chosen is not None and student.student_id not in chosen:
                    continue
                existing = signatures.get((student.student_id, template.lineage))
                path, missing_dob = _path_for(student, sections, now)
                if (
                    existing
                    and _counts(existing, template, path, now)
                    and _signed_by(existing, parent_id)
                ):
                    continue
                if missing_dob:
                    no_birth_date.append(student.student_name)
                    continue
                planned.append((template, student, path))
        if no_birth_date:
            raise WaiverDateOfBirthMissing(
                "Add a date of birth for " + ", ".join(sorted(set(no_birth_date))) + " to sign.",
                students=sorted(set(no_birth_date)),
            )
        given = initials or {}
        unmet = {
            template.waiver_template_id: keys
            for template, _, path in planned
            if (
                keys := missing_initials(
                    parse_sections(template.body), path, given.get(template.waiver_template_id, {})
                )
            )
        }
        if unmet:
            raise WaiverSignatureIncomplete(
                "Initial every section marked for initials to sign.", missing_initials=unmet
            )
        # Request-time tenant via the injected provider — never a boot-time value.
        academy_id = self._academy_id()
        created: list[str] = []
        for template, student, path in planned:
            signature = WaiverSignature(
                waiver_signature_id=self._id_factory(),
                academy_id=academy_id,
                waiver_template_id=template.waiver_template_id,
                student_id=student.student_id,
                parent_user_id=parent_id,
                signed_at=now,
                signer_name=name,
                signer_email=signer_email,
                content_hash=template.content_hash or "",
                ip_address=ip_address,
                user_agent=user_agent,
                consent_text=ESIGN_CONSENT_TEXT,
                initials={
                    key: value.strip().upper()
                    for key, value in given.get(template.waiver_template_id, {}).items()
                    if value.strip()
                },
                signing_path=path,
            )
            await self._waivers.save_signature(signature)
            created.append(signature.waiver_signature_id)

        # Only newly created signatures get a receipt, so a retried request
        # that signs nothing new sends nothing.
        if created and self._notifier is not None:
            try:
                await self._notifier.waivers_signed(
                    parent_user_id=parent_id,
                    signer_email=signer_email,
                    waiver_signature_ids=created,
                )
            except Exception:
                logger.exception("waiver.receipt_email_failed", extra={"parent_id": parent_id})

        signatures = await self._waivers.signatures_for_students(
            [student.student_id for student in required.students]
        )
        return _requirement_view(required, signatures, parent_id=parent_id, now=now)


class GetParentSignedWaiver:
    """A parent's own signed copy. Anyone else's reads as not found (404)."""

    def __init__(self, *, waivers: ParentWaiverRepository) -> None:
        self._waivers = waivers

    async def execute(self, *, parent_id: str, waiver_signature_id: str) -> ParentSignedWaiverCopy:
        copy = await self._waivers.signed_copy(waiver_signature_id)
        if copy is None:
            raise WaiverSignatureNotFound("Signed waiver not found")
        if copy.parent_user_id != parent_id:
            # Rows from before signer tracking have no parent: allow the
            # child's current guardian, nobody else.
            own = {
                s.student_id for s in await self._waivers.list_active_students_for_parent(parent_id)
            }
            if copy.parent_user_id is not None or copy.student_id not in own:
                raise WaiverSignatureNotFound("Signed waiver not found")
        return copy


def _requirement_view(
    required: _RequiredSet,
    signatures: dict[tuple[str, str], ParentWaiverSignature],
    *,
    parent_id: str,
    now: datetime,
) -> ParentWaiverRequirement:
    items = [
        ParentWaiverItem(
            waiver_template_id=template.waiver_template_id,
            title=template.title,
            version=template.version,
            body=template.body,
            students=[
                _student_status(
                    student,
                    template,
                    signatures.get((student.student_id, template.lineage)),
                    parent_id=parent_id,
                    now=now,
                )
                for student in covered
            ],
        )
        for template, covered in required.waivers
    ]
    first = items[0]
    return ParentWaiverRequirement(
        required=True,
        waiver_template_id=first.waiver_template_id,
        title=first.title,
        version=first.version,
        body=first.body,
        students=first.students,
        waivers=items,
    )


def _student_status(
    student: ParentWaiverStudent,
    template: AdminWaiverTemplateRecord,
    signature: ParentWaiverSignature | None,
    *,
    parent_id: str,
    now: datetime,
) -> ParentWaiverStudentStatus:
    path, missing_dob = _path_for(student, parse_sections(template.body), now)
    if signature is None:
        status: ParentWaiverStatus = "pending"
    elif _counts(signature, template, path, now) and _signed_by(signature, parent_id):
        status = "signed"
    else:
        status = "outdated"
    return ParentWaiverStudentStatus(
        student_id=student.student_id,
        student_name=student.student_name,
        status=status,
        signed_at=signature.signed_at if signature else None,
        waiver_version=signature.waiver_version or template.version if signature else None,
        waiver_signature_id=signature.waiver_signature_id if signature else None,
        signing_path=path,
        date_of_birth_missing=missing_dob,
    )


def _path_for(
    student: ParentWaiverStudent, sections: list[Any], now: datetime
) -> tuple[SigningPath | None, bool]:
    """(signing path, date of birth missing) for this child and waiver."""
    if not has_age_paths(sections):
        return None, False
    # shortcut: the UTC date, not the academy's; only differs within hours of
    # an 18th birthday. Upgrade if an academy far from UTC needs the exact day.
    path = signing_path_for(student.date_of_birth, now.date())
    return path, path is None


def _counts(
    signature: ParentWaiverSignature,
    template: AdminWaiverTemplateRecord,
    path: SigningPath | None,
    now: datetime,
) -> bool:
    """A signature still covers this child: same wording, not expired, and not
    a minor-path signature for a participant who has since turned 18."""
    if not signature_is_current(signature, template, now=now):
        return False
    return not (signature.signing_path == "minor" and path == "adult")


def _signed_by(signature: ParentWaiverSignature, parent_id: str) -> bool:
    """True when this signature is the *requesting* parent's own consent.

    Issue #785: signatures are keyed by student, so an admin moving a child to
    a new guardian left the new parent's page reading "signed" off the previous
    parent's consent — and `AcceptParentWaiver` skipped the child, so the
    academy held no waiver from the person who now has custody.

    A row with no recorded signer predates the field and is left alone: a
    blanket re-sign prompt for every legacy family is worse than the gap.
    """
    if signature.outdated_for_parent:
        return False
    if signature.parent_user_id is None:
        return True
    return signature.parent_user_id == parent_id


def signature_is_current(
    signature: ParentWaiverSignature,
    template: AdminWaiverTemplateRecord,
    *,
    now: datetime | None = None,
) -> bool:
    """Whether an older-or-equal signature still counts for this live version.

    Same content hash counts; without hashes the same template id or version
    does. A signature for an older version with different wording does not, and
    neither does one past the waiver's renewal period or end date.
    """
    return _is_current(signature, template) and not signature_expired(signature, template, now=now)


def signature_expired(
    signature: ParentWaiverSignature,
    template: AdminWaiverTemplateRecord,
    *,
    now: datetime | None = None,
) -> bool:
    return template.assignment.expired(signature.signed_at, now or datetime.now(UTC))


def _is_current(
    signature: ParentWaiverSignature,
    template: AdminWaiverTemplateRecord,
) -> bool:
    if signature.content_hash and template.content_hash:
        return signature.content_hash == template.content_hash
    if signature.waiver_template_id and signature.waiver_template_id == template.waiver_template_id:
        return True
    return bool(signature.waiver_version and signature.waiver_version == template.version)
