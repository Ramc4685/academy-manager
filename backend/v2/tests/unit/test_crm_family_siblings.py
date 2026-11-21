"""The family's "Siblings" marker: two or more children with a live class."""

from __future__ import annotations

import pytest

from backend.v2.contexts.crm.domain.family_index import FamilyChild, FamilyRecord


def _record(*lifecycles: str) -> FamilyRecord:
    return FamilyRecord(
        family_id="fam-1",
        parent_name="Pat Example",
        email=None,
        phone=None,
        has_account=True,
        children=tuple(
            FamilyChild(student_id=f"stu-{i}", name=f"Kid {i}", lifecycle=state)
            for i, state in enumerate(lifecycles)
        ),
        stage="active",
    )


@pytest.mark.parametrize(
    ("lifecycles", "expected"),
    [
        (("active", "paused"), ("stu-0", "stu-1")),
        (("at_risk", "on_hold", "pending_cancel"), ("stu-0", "stu-1", "stu-2")),
        (("active", "left"), ()),
        (("active", "trial"), ()),
        (("active",), ()),
        (("left", "never_enrolled"), ()),
        (("active", "left", "paused"), ("stu-0", "stu-2")),
    ],
)
def test_siblings_are_two_or_more_enrolled_children(
    lifecycles: tuple[str, ...], expected: tuple[str, ...]
) -> None:
    assert _record(*lifecycles).sibling_student_ids == expected
