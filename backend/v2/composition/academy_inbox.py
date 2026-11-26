"""The academy inbox (D-18): which admin DMs join a family's shared thread.

Page-scoped so ``composition/admin.py`` (at its line budget) stays untouched.
The admin DM route asks this whether a recipient is a parent of the request's
academy; if so the reply is stamped into that family's thread, visible to every
admin, and carries the staff member's name for the other admins.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from backend.v2.composition.push import compose_roles_of

#: Roles a recipient may hold for a staff DM to join the shared family thread.
FAMILY_ROLES = frozenset({"parent", "student"})


@dataclass
class AcademyInbox:
    roles_of: Callable[[str, str], Awaitable[Sequence[str]]]
    users: Any  # MongoUserRepository: get_by_id(user_id) -> User | None

    async def thread_for(self, academy_id: str, recipient_id: str) -> str | None:
        """The academy-inbox thread a staff DM to ``recipient_id`` belongs to:
        the parent's own id, or ``None`` (the DM stays private to its two ends).

        Parent-only on purpose: a parent who is also a coach or staff member
        could be getting a private staff DM, and joining it to the shared
        thread would show it to every admin. Their own messages to the academy
        still land in the thread; staff replies to them stay private.
        """
        roles = set(await self.roles_of(academy_id, recipient_id))
        return recipient_id if "parent" in roles and roles <= FAMILY_ROLES else None

    async def staff_name(self, user_id: str) -> str | None:
        user = await self.users.get_by_id(user_id)
        name = str(getattr(user, "display_name", "") or "").strip()
        return name or None


def compose_academy_inbox(db: Any, settings: Any) -> AcademyInbox:
    from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository

    return AcademyInbox(roles_of=compose_roles_of(db, settings), users=MongoUserRepository(db))
