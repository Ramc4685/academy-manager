"""Which parent/student profile details are still missing.

The required set spans two bounded contexts — parent fields live in
``identity``, child fields in ``enrollment`` — and contexts may not import one
another (``tests/structural/test_layering.py``), so the rule lives here and
takes plain values. Nothing in this module may import from ``contexts``.

Gap keys are stable strings; the frontend maps them to labels.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel, Field

# Written into ``medical_notes`` when a parent ticks "no known conditions or
# allergies". An empty field cannot mean "nothing to declare" — it is
# indistinguishable from "never asked" — so the answer needs a value of its own.
MEDICAL_NONE_SENTINEL = "__none_declared__"

PARENT_REQUIRED: tuple[str, ...] = (
    "display_name",
    "phone",
    "email_confirmed",
)

CHILD_REQUIRED: tuple[str, ...] = (
    "full_name",
    "date_of_birth",
    "emergency_contact_name",
    "emergency_contact_phone",
    "medical_notes",
)


def _blank(value: str | None) -> bool:
    """A value is missing if it is absent or only whitespace."""

    return value is None or not value.strip()


class ParentFacts(BaseModel):
    model_config = {"frozen": True}

    display_name: str | None = None
    phone: str | None = None
    email_confirmed_at: datetime | None = None


class ChildFacts(BaseModel):
    model_config = {"frozen": True}

    student_id: str
    full_name: str | None = None
    date_of_birth: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    medical_notes: str | None = None


class ProfileGaps(BaseModel):
    model_config = {"frozen": True}

    parent: list[str] = Field(default_factory=list)
    children: dict[str, list[str]] = Field(default_factory=dict)

    @property
    def is_complete(self) -> bool:
        return not self.parent and not any(self.children.values())

    @property
    def total(self) -> int:
        return len(self.parent) + sum(len(gaps) for gaps in self.children.values())


def medical_notes_answered(value: str | None) -> bool:
    """True when the parent has either declared "none" or written something."""

    return not _blank(value)


def parent_gaps(parent: ParentFacts) -> list[str]:
    gaps: list[str] = []
    if _blank(parent.display_name):
        gaps.append("display_name")
    if _blank(parent.phone):
        gaps.append("phone")
    if parent.email_confirmed_at is None:
        gaps.append("email_confirmed")
    return gaps


def child_gaps(child: ChildFacts) -> list[str]:
    gaps: list[str] = []
    if _blank(child.full_name):
        gaps.append("full_name")
    if _blank(child.date_of_birth):
        gaps.append("date_of_birth")
    if _blank(child.emergency_contact_name):
        gaps.append("emergency_contact_name")
    if _blank(child.emergency_contact_phone):
        gaps.append("emergency_contact_phone")
    if not medical_notes_answered(child.medical_notes):
        gaps.append("medical_notes")
    return gaps


def evaluate(parent: ParentFacts, children: Sequence[ChildFacts]) -> ProfileGaps:
    """Report every required field still missing for a parent and their children."""

    return ProfileGaps(
        parent=parent_gaps(parent),
        children={child.student_id: child_gaps(child) for child in children},
    )
