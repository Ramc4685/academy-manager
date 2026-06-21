"""Clean SaaS tenant bootstrap use case.

This use case creates the initial v2-only tenant records for a new academy.
It intentionally depends on a protocol instead of concrete Mongo
repositories so Agent A's membership repository can be wired in later without
duplicating that implementation here.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, EmailStr, Field, field_validator

from backend.v2.contexts.identity.domain.models import Role, normalize_email
from backend.v2.shared.http.errors import DomainError
from backend.v2.shared.ids import new_ulid

OWNER_ACADEMY_ROLE: Role = "admin"
DEFAULT_RECORDS = (
    "academy",
    "owner_user",
    "owner_membership",
    "academy_settings",
    "billing_policy",
    "waiver_template",
    "roles",
    "feature_flags",
)


class BootstrapSlugConflict(DomainError):
    code = "Identity.BootstrapSlugConflict"
    status_code = 409


class BootstrapDomainConflict(DomainError):
    code = "Identity.BootstrapDomainConflict"
    status_code = 409


class TenantBootstrapStore(Protocol):
    """Storage port used by BootstrapAcademy.

    Implementations should route tenant-owned writes through v2
    infrastructure/repositories. The application layer never talks to Mongo
    collections directly.
    """

    async def find_academy_by_slug(self, slug: str) -> dict[str, Any] | None: ...
    async def find_academy_by_domain(self, domain: str) -> dict[str, Any] | None: ...
    async def create_academy(self, academy: dict[str, Any]) -> dict[str, Any]: ...
    async def ensure_owner_user(self, user: dict[str, Any]) -> dict[str, Any]: ...
    async def ensure_owner_membership(self, membership: dict[str, Any]) -> dict[str, Any]: ...
    async def ensure_academy_settings(self, settings: dict[str, Any]) -> dict[str, Any]: ...
    async def ensure_billing_policy(self, policy: dict[str, Any]) -> dict[str, Any]: ...
    async def ensure_waiver_template(self, waiver: dict[str, Any]) -> dict[str, Any]: ...
    async def ensure_default_roles(
        self, academy_id: str, roles: list[dict[str, Any]]
    ) -> list[dict[str, Any]]: ...
    async def ensure_feature_flags(self, flags: dict[str, Any]) -> dict[str, Any]: ...


class BootstrapAcademyCommand(BaseModel):
    display_name: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    primary_domain: str = Field(min_length=1)
    owner_email: EmailStr
    owner_display_name: str = Field(min_length=1)
    timezone: str = Field(default="UTC", min_length=1)

    @field_validator("display_name", "owner_display_name", "timezone")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("slug")
    @classmethod
    def _normalize_slug(cls, value: str) -> str:
        normalized = value.strip().lower().replace("_", "-")
        normalized = "-".join(part for part in normalized.split("-") if part)
        if not normalized:
            raise ValueError("slug is required")
        return normalized

    @field_validator("primary_domain")
    @classmethod
    def _normalize_domain(cls, value: str) -> str:
        normalized = value.strip().lower().rstrip(".")
        if not normalized:
            raise ValueError("primary_domain is required")
        return normalized

    @field_validator("owner_email")
    @classmethod
    def _normalize_owner_email(cls, value: EmailStr) -> str:
        return normalize_email(str(value))


class BootstrapAcademyResult(BaseModel):
    academy_id: str
    slug: str
    primary_domain: str
    owner_user_id: str
    membership_id: str
    owner_role: Role
    created: bool
    default_records: tuple[str, ...] = DEFAULT_RECORDS


class BootstrapAcademy:
    def __init__(
        self,
        *,
        store: TenantBootstrapStore,
        id_factory: Callable[[str], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._id_factory = id_factory or (lambda prefix: f"{prefix}{new_ulid()}")
        self._clock = clock or (lambda: datetime.now(UTC))

    async def execute(self, command: BootstrapAcademyCommand) -> BootstrapAcademyResult:
        slug_match = await self._store.find_academy_by_slug(command.slug)
        domain_match = await self._store.find_academy_by_domain(command.primary_domain)

        existing = self._resolve_existing_or_raise(command, slug_match, domain_match)
        if existing is not None:
            return await self._ensure_defaults(command, existing, created=False)

        now = self._clock()
        academy = {
            "academy_id": self._id_factory("acad_"),
            "slug": command.slug,
            "primary_domain": command.primary_domain,
            "display_name": command.display_name,
            "timezone": command.timezone,
            "status": "active",
            "owner_email": str(command.owner_email),
            "created_at": now,
            "updated_at": now,
        }
        created = await self._store.create_academy(academy)
        return await self._ensure_defaults(command, created, created=True)

    def _resolve_existing_or_raise(
        self,
        command: BootstrapAcademyCommand,
        slug_match: dict[str, Any] | None,
        domain_match: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if slug_match is None and domain_match is None:
            return None

        if slug_match is not None and domain_match is not None:
            if slug_match["academy_id"] != domain_match["academy_id"]:
                raise BootstrapSlugConflict(f"academy slug already exists: {command.slug}")
            if str(slug_match.get("owner_email")) == str(command.owner_email):
                return slug_match
            raise BootstrapSlugConflict(f"academy slug already exists: {command.slug}")

        if slug_match is not None:
            raise BootstrapSlugConflict(f"academy slug already exists: {command.slug}")
        raise BootstrapDomainConflict(f"academy domain already exists: {command.primary_domain}")

    async def _ensure_defaults(
        self,
        command: BootstrapAcademyCommand,
        academy: dict[str, Any],
        *,
        created: bool,
    ) -> BootstrapAcademyResult:
        now = self._clock()
        academy_id = str(academy["academy_id"])
        owner_email = str(command.owner_email)

        owner = await self._store.ensure_owner_user(
            {
                "user_id": self._id_factory("user_"),
                "email": owner_email,
                "normalized_email": normalize_email(owner_email),
                "display_name": command.owner_display_name,
                "global_status": "active",
                "created_at": now,
                "updated_at": now,
            }
        )
        owner_user_id = str(owner["user_id"])
        membership = await self._store.ensure_owner_membership(
            {
                "membership_id": self._id_factory("membership_"),
                "academy_id": academy_id,
                "user_id": owner_user_id,
                "roles": [OWNER_ACADEMY_ROLE],
                "status": "active",
                "accepted_at": now,
                "created_at": now,
                "updated_at": now,
            }
        )
        await self._store.ensure_academy_settings(
            {
                "settings_id": self._id_factory("settings_"),
                "academy_id": academy_id,
                "display_name": command.display_name,
                "timezone": command.timezone,
                "locale": "en-US",
                "created_at": now,
                "updated_at": now,
            }
        )
        await self._store.ensure_billing_policy(
            {
                "policy_id": self._id_factory("policy_"),
                "academy_id": academy_id,
                "currency": "usd",
                "invoice_day": 1,
                "grace_period_days": 5,
                "auto_charge_enabled": False,
                "created_at": now,
                "updated_at": now,
            }
        )
        await self._store.ensure_waiver_template(_default_waiver(academy_id, now, self._id_factory))
        await self._store.ensure_default_roles(academy_id, _default_roles(academy_id, now))
        await self._store.ensure_feature_flags(
            {
                "feature_flags_id": self._id_factory("flags_"),
                "academy_id": academy_id,
                "saas_v2_enabled": True,
                "billing_enabled": False,
                "messaging_enabled": False,
                "created_at": now,
                "updated_at": now,
            }
        )

        return BootstrapAcademyResult(
            academy_id=academy_id,
            slug=str(academy["slug"]),
            primary_domain=str(academy["primary_domain"]),
            owner_user_id=owner_user_id,
            membership_id=str(membership["membership_id"]),
            owner_role=OWNER_ACADEMY_ROLE,
            created=created,
        )


def _default_waiver(
    academy_id: str,
    now: datetime,
    id_factory: Callable[[str], str],
) -> dict[str, Any]:
    text = (
        "Default academy participation waiver. Replace this template before "
        "accepting student registrations."
    )
    return {
        "waiver_template_id": id_factory("wt_"),
        "academy_id": academy_id,
        "name": "Default participation waiver",
        "title": "Default participation waiver",
        "version": "1",
        "body": text,
        "status": "active",
        "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "effective_from": now,
        "published_at": now,
        "assigned_to_registration": True,
        "assigned_at": now,
        "created_at": now,
        "updated_at": now,
    }


def _default_roles(academy_id: str, now: datetime) -> list[dict[str, Any]]:
    return [
        {
            "academy_id": academy_id,
            "role": "admin",
            "display_name": "Admin",
            "permissions": ["academy.manage", "billing.manage", "members.manage"],
            "created_at": now,
            "updated_at": now,
        },
        {
            "academy_id": academy_id,
            "role": "coach",
            "display_name": "Coach",
            "permissions": ["sessions.coach", "attendance.write"],
            "created_at": now,
            "updated_at": now,
        },
        {
            "academy_id": academy_id,
            "role": "parent",
            "display_name": "Parent",
            "permissions": ["children.read", "payments.read"],
            "created_at": now,
            "updated_at": now,
        },
    ]
