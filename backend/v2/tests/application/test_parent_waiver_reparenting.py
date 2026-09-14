"""A re-parented student's waiver must be re-signed by the new guardian (#785).

``latest_signatures_for_students`` keys only by ``student_id``, so after an
admin moved a child to a different parent the new parent's waiver page read
"signed" off a signature a *stranger* had given — and ``AcceptParentWaiver``
skipped the child entirely, so the academy held no consent from the person who
now has custody.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.onboarding.application.use_cases.admin_waiver_templates import (
    AdminWaiverTemplateRecord,
)
from backend.v2.contexts.onboarding.application.use_cases.parent_student_waivers import (
    AcceptParentWaiver,
    GetParentWaiverRequirement,
    ParentWaiverSignature,
    ParentWaiverStudent,
)
from backend.v2.contexts.onboarding.domain.models import WaiverSignature

NOW = datetime(2026, 6, 21, 12, 0, tzinfo=UTC)
TEMPLATE = AdminWaiverTemplateRecord(
    waiver_template_id="wt-1",
    title="Annual waiver",
    body="Parent agrees to academy safety rules.",
    status="active",
    version="2026.1",
    content_hash="hash-2026",
    assigned_to_registration=True,
    updated_at=NOW,
)


class FakeParentWaiverRepo:
    def __init__(self, signatures: dict[str, ParentWaiverSignature]) -> None:
        self._signatures = dict(signatures)
        self.saved: list[WaiverSignature] = []

    async def get_required_template(self) -> AdminWaiverTemplateRecord | None:
        return TEMPLATE

    async def list_active_students_for_parent(self, parent_id: str) -> list[ParentWaiverStudent]:
        return [ParentWaiverStudent(student_id="st-1", student_name="Alice Chen")]

    async def latest_signatures_for_students(
        self, student_ids: list[str]
    ) -> dict[str, ParentWaiverSignature]:
        return {k: v for k, v in self._signatures.items() if k in student_ids}

    async def save_signature(self, signature: WaiverSignature) -> None:
        self.saved.append(signature)
        self._signatures[signature.student_id] = ParentWaiverSignature(
            student_id=signature.student_id,
            waiver_template_id=signature.waiver_template_id,
            content_hash=signature.content_hash,
            parent_user_id=signature.parent_user_id,
            signed_at=signature.signed_at,
        )


def _inherited_signature(**overrides: object) -> ParentWaiverSignature:
    fields: dict[str, object] = {
        "student_id": "st-1",
        "waiver_template_id": "wt-1",
        "content_hash": "hash-2026",
        "parent_user_id": "parent-old",
        "signed_at": NOW,
    }
    fields.update(overrides)
    return ParentWaiverSignature(**fields)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_signature_from_a_previous_guardian_reads_as_outdated() -> None:
    repo = FakeParentWaiverRepo({"st-1": _inherited_signature()})

    requirement = await GetParentWaiverRequirement(waivers=repo).execute(parent_id="parent-new")

    assert [student.status for student in requirement.students] == ["outdated"]


@pytest.mark.asyncio
async def test_signature_stamped_outdated_by_a_parent_change_reads_as_outdated() -> None:
    repo = FakeParentWaiverRepo(
        {"st-1": _inherited_signature(parent_user_id=None, outdated_for_parent=True)}
    )

    requirement = await GetParentWaiverRequirement(waivers=repo).execute(parent_id="parent-new")

    assert [student.status for student in requirement.students] == ["outdated"]


@pytest.mark.asyncio
async def test_the_signing_parents_own_current_signature_still_reads_as_signed() -> None:
    repo = FakeParentWaiverRepo({"st-1": _inherited_signature(parent_user_id="parent-new")})

    requirement = await GetParentWaiverRequirement(waivers=repo).execute(parent_id="parent-new")

    assert [student.status for student in requirement.students] == ["signed"]


@pytest.mark.asyncio
async def test_accepting_re_signs_a_child_whose_signature_belongs_to_the_old_parent() -> None:
    repo = FakeParentWaiverRepo({"st-1": _inherited_signature()})

    requirement = await AcceptParentWaiver(
        waivers=repo,
        academy_id=lambda: "test-academy",
        id_factory=lambda: "ws-new",
        clock=lambda: NOW,
    ).execute(
        parent_id="parent-new",
        signer_name="Parent New",
        signer_email="new@example.com",
        ip_address=None,
        user_agent=None,
    )

    assert [signature.parent_user_id for signature in repo.saved] == ["parent-new"]
    assert [student.status for student in requirement.students] == ["signed"]
