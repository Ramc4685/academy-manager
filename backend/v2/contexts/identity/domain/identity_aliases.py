"""The identifiers one account may be keyed by, in one place.

`users.user_id` and `academy_memberships.user_id` are supposed to hold the
same value, but `ensure_parent_login` / `ensure_student_login` preserve a
pre-existing roster `user_id` on the users doc while keying the new
membership row by the freshly provisioned `firebase_uid`, so the two
legitimately diverge — in either direction, and a doc may carry a stale
`auth_uid` alongside a newer `firebase_uid`.

Every read that resolves a membership from an account (login, login invite,
membership listing) must consider the same alias set, or the checks disagree
and a parent signs in successfully and is then rejected. Divergent per-module
copies of this list are how that bug class recurs, so both repositories and
`load_auth_claims` share these helpers.

Aliases widen only the *identity* side of a query. Callers keep `academy_id`
as an explicit, mandatory term; alias matching never widens tenant scope.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def identity_aliases(*values: object) -> tuple[str, ...]:
    """Ordered, de-duplicated, falsy-stripped identifiers.

    Order is preserved so callers can express a preference (the primary id
    first) and rank matches deterministically.
    """
    return tuple(dict.fromkeys(str(value) for value in values if value))


def aliases_from_doc(doc: Mapping[str, Any]) -> tuple[str, ...]:
    """Every identifier a raw `users` document might be keyed by."""
    return identity_aliases(doc.get("user_id"), doc.get("auth_uid"), doc.get("firebase_uid"))
