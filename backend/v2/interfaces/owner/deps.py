"""Owner BFF dependencies.

Note there is deliberately no `require_owner` persona guard. Persona checks
read `claims.roles`, which is scoped to the single academy the request
resolved to — an owner of academies A and B must be able to read the rollup
regardless of which of them the tenant header names. Scope comes from the
caller's memberships instead, resolved inside the use case, which raises
`NotAFranchiseOwner` when there are none. Any future route in this package
must derive its scope from `claims.user_id` the same way; do not add a
dependency that looks like an authorization guard but is not one.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from backend.v2.composition.owner import OwnerComposition


def get_owner_use_cases(request: Request) -> OwnerComposition:
    composition = getattr(request.app.state, "owner", None)
    if composition is None:
        # Flag off / not wired: behave as if the surface does not exist.
        raise HTTPException(status_code=404, detail="Not found")
    return composition  # type: ignore[no-any-return]
