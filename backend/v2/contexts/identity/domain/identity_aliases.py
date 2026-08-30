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


def membership_match_rank(doc: Mapping[str, Any], user_id: str) -> tuple[int, int, str]:
    """Deterministic ordering over `academy_memberships` rows matched by alias.

    Lives beside the alias helpers for the same reason they do: the read path
    (`get_membership`, and through it `load_auth_claims`) and the write paths
    that have to revoke what that read grants must agree on *which* row is the
    live one, or a revocation rewrites a row auth never looks at. Ranking:

    1. active status wins — a live membership beats a stale row whatever it is
       keyed by (this is the row auth must see);
    2. then an exact `user_id` hit beats an alias hit;
    3. then `membership_id`, so the result is stable even for rows that tie,
       rather than depending on Mongo's natural order.
    """
    status_rank = 0 if str(doc.get("status", "active")) == "active" else 1
    exact_rank = 0 if str(doc.get("user_id", "")) == user_id else 1
    tiebreak = str(doc.get("membership_id") or doc.get("_id") or "")
    return (status_rank, exact_rank, tiebreak)
