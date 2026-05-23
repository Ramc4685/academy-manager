"""Public registration routes.

These endpoints are intentionally narrow. They accept a valid Firebase token
but do not require a pre-existing Mongo authorization row, because they create
that row for first-time parent onboarding.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.v2.contexts.identity.application.use_cases.register_public_parent import (
    RegisterPublicParent,
)
from backend.v2.shared.auth.claims import Role

router = APIRouter(prefix="/register", tags=["registration"])


class RegisterParentResponse(BaseModel):
    user_id: str
    email: str
    academy_id: str
    roles: tuple[Role, ...]


@router.post("/parent", response_model=RegisterParentResponse)
async def register_parent(request: Request) -> RegisterParentResponse:
    token = _extract_bearer(request)
    if token is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Resolve the tenant the parent is registering against. The middleware
    # already computed this from the request host (subdomain / custom
    # domain / approved internal header) and stored it on request.state.
    # In SaaS mode an unresolved tenant is a client error (400) — we
    # MUST NOT fall back to ``default-academy`` here (fixes #81).
    resolved_academy_id: str | None = getattr(request.state, "resolved_academy_id", None)
    saas_mode = bool(getattr(request.app.state, "saas_mode", False))
    if saas_mode and not resolved_academy_id:
        raise HTTPException(
            status_code=400,
            detail="Tenant could not be resolved from the request host",
        )

    use_case: RegisterPublicParent = request.app.state.register_public_parent
    user = await use_case.execute(token, academy_id=resolved_academy_id)
    return RegisterParentResponse(
        user_id=user.user_id,
        email=user.email,
        academy_id=user.academy_id,
        roles=user.roles,
    )


def _extract_bearer(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if not header:
        return None
    parts = header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None
