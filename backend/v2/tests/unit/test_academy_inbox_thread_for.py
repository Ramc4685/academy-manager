"""A staff DM joins the shared academy-inbox thread only for a parent-only
recipient (S61 follow-up): a dual-role parent+coach/staff member's DMs stay
private, so they never become visible to every admin."""

from __future__ import annotations

import pytest

from backend.v2.composition.academy_inbox import AcademyInbox


def _inbox(roles: tuple[str, ...]) -> AcademyInbox:
    async def roles_of(academy_id: str, user_id: str) -> tuple[str, ...]:
        assert academy_id == "acad"
        return roles

    return AcademyInbox(roles_of=roles_of, users=None)


@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        (("parent",), "u1"),
        (("parent", "student"), "u1"),
        (("parent", "coach"), None),
        (("parent", "admin"), None),
        (("parent", "front_desk"), None),
        (("coach",), None),
        ((), None),
    ],
)
async def test_thread_for_is_parent_only(roles, expected):
    assert await _inbox(roles).thread_for("acad", "u1") == expected
