"""Who an audit row's actor is, in one academy's terms (#468).

`audit_logs` rows store a bare `actor_id`. Rendering "who did this" needs a
name and a role, and the role is per-academy-membership — a user can be a coach
here and a parent there. These helpers hold the two rules that decision needs:
which role wins when an actor holds several, and what an unresolvable actor
should be called.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import BaseModel

# Most privileged first: the audit trail names the strongest role the actor
# holds, so "who could have done this" is never understated.
ACTOR_TYPE_BY_ROLE: tuple[tuple[str, str], ...] = (
    ("owner", "owner"),
    ("admin", "admin"),
    ("coach", "coach"),
    ("assistant_coach", "coach"),
    ("parent", "parent"),
    ("student", "parent"),
)


class AuditActor(BaseModel, frozen=True):
    """One resolved actor: their display name and roles in *this* academy."""

    name: str | None = None
    roles: tuple[str, ...] = ()


def audit_actor_fields(actor_id: object, actors: Mapping[str, AuditActor]) -> dict[str, str | None]:
    """The `actor_type` / `actor_role` / `actor_name` for one audit row.

    No actor id at all means the platform itself acted. An actor we cannot
    resolve to a membership in this academy still reads as `admin`: that is
    what the page said before #468, and demoting a legacy row to "system"
    would misattribute a human action to the platform.
    """
    if not actor_id:
        return {"actor_type": "system", "actor_role": None, "actor_name": "System"}

    resolved = actors.get(str(actor_id)) or AuditActor()
    roles = set(resolved.roles)
    actor_type = next((mapped for role, mapped in ACTOR_TYPE_BY_ROLE if role in roles), "admin")
    ordered = [role for role, _ in ACTOR_TYPE_BY_ROLE if role in roles]
    return {
        "actor_type": actor_type,
        "actor_role": ", ".join(ordered) or None,
        "actor_name": resolved.name or None,
    }


def actor_type_of(roles: Sequence[str]) -> str:
    """The single actor type a set of academy roles collapses to."""
    held = set(roles)
    return next((mapped for role, mapped in ACTOR_TYPE_BY_ROLE if role in held), "admin")
