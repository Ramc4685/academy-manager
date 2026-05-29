"""Public parent registration use case.

Firebase proves identity. This use case bootstraps the lowest-privilege
auth rows required for a parent to begin onboarding inside the resolved
tenant.

SaaS mode (``saas_mode=True``)
------------------------------
* ``academy_id`` is required at the call site (resolved by the route
  from the request host).
* Creates the global ``User`` row plus an active ``AcademyMembership``
  row ``(academy_id, user_id, roles=("parent",), status="active")``.
* ``User.academy_id`` is set to the resolved tenant on first insert
  (legacy field; SaaS reads come from the membership). Existing users
  keep their original ``User.academy_id``; multi-tenant access is
  carried entirely by the membership row.

Single-tenant fallback (``saas_mode=False``)
--------------------------------------------
* ``academy_id`` is omitted and the configured ``default_academy_id``
  is used so existing single-tenant deployments keep working.
* No membership row is created; legacy ``User.academy_id`` carries
  authorization.

Fixes #81 (parent registration wrote ``default-academy`` regardless of
the resolved tenant in SaaS mode).
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel

from backend.v2.contexts.identity.application.ports import (
    MembershipRepository,
    PublicParentRegistrationRepository,
    TokenVerifier,
)
from backend.v2.contexts.identity.domain.errors import InvalidToken, UserInactive
from backend.v2.contexts.identity.domain.models import AcademyMembership, User
from backend.v2.shared.events import DomainEvent, Outbox
from backend.v2.shared.ids import new_ulid

log = logging.getLogger(__name__)


class WelcomeEmailRequestedPayload(BaseModel):
    user_id: str
    email: str
    display_name: str


class WelcomeEmailRequested(DomainEvent):
    name: Literal["Identity.WelcomeEmailRequested"] = "Identity.WelcomeEmailRequested"
    schema_version: Literal[1] = 1
    payload: WelcomeEmailRequestedPayload


class RegisterPublicParent:
    def __init__(
        self,
        *,
        verifier: TokenVerifier,
        users: PublicParentRegistrationRepository,
        memberships: MembershipRepository | None = None,
        outbox: Outbox | None = None,
        default_academy_id: str = "default-academy",
        saas_mode: bool = False,
    ) -> None:
        if saas_mode and memberships is None:
            raise ValueError(
                "RegisterPublicParent requires a memberships repository when saas_mode is True"
            )
        self._verifier = verifier
        self._users = users
        self._memberships = memberships
        self._outbox = outbox
        self._default_academy_id = default_academy_id
        self._saas_mode = saas_mode

    async def execute(self, id_token: str, *, academy_id: str | None = None) -> User:
        try:
            token_claims = await self._verifier.verify(id_token)
        except Exception as exc:
            raise InvalidToken(str(exc)) from exc

        email = token_claims.get("email")
        if not isinstance(email, str) or not email:
            raise InvalidToken("token missing email")
        _require_verified_password_provider_email(token_claims)

        uid = token_claims.get("uid") or token_claims.get("sub")
        if not isinstance(uid, str) or not uid:
            raise InvalidToken("token missing uid")

        display_name = token_claims.get("name")
        if not isinstance(display_name, str) or not display_name.strip():
            display_name = email

        # Tenant resolution. The route is the source of truth for the
        # resolved tenant; we only fall back to default_academy_id in
        # the legacy single-tenant branch. In SaaS mode a missing
        # academy_id is a programmer error (the route should 400 first).
        if academy_id is None:
            if self._saas_mode:
                raise InvalidToken("tenant required for parent registration in SaaS mode")
            target_academy_id = self._default_academy_id
        else:
            target_academy_id = academy_id

        existing = await self._users.get_by_email(email)
        if existing is not None and not existing.is_active:
            raise UserInactive(f"user {existing.user_id} disabled")

        user = await self._users.ensure_parent_user(
            email=email,
            display_name=display_name.strip(),
            firebase_uid=uid,
            academy_id=target_academy_id,
        )

        if self._memberships is not None:
            await self._memberships.upsert_membership(
                AcademyMembership(
                    membership_id=new_ulid(),
                    academy_id=target_academy_id,
                    user_id=user.user_id,
                    roles=("parent",),
                    status="active",
                )
            )

        if existing is None and self._outbox is not None:
            try:
                await self._outbox.append(
                    WelcomeEmailRequested(
                        aggregate_id=user.user_id,
                        academy_id=target_academy_id,
                        payload=WelcomeEmailRequestedPayload(
                            user_id=user.user_id,
                            email=str(user.email),
                            display_name=user.display_name,
                        ),
                    )
                )
            except Exception:
                log.exception(
                    "welcome_email_request_failed",
                    extra={
                        "user_id": user.user_id,
                        "academy_id": target_academy_id,
                    },
                )

        return user


def _require_verified_password_provider_email(token_claims: dict[str, object]) -> None:
    firebase_claims = token_claims.get("firebase")
    provider = None
    if isinstance(firebase_claims, dict):
        provider = firebase_claims.get("sign_in_provider")
    if provider == "password" and token_claims.get("email_verified") is not True:
        raise InvalidToken("email must be verified")
