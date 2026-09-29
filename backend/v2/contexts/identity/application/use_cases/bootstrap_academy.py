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
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, EmailStr, Field, field_validator

from backend.v2.contexts.identity.domain.models import Role, normalize_email
from backend.v2.shared.http.errors import DomainError
from backend.v2.shared.ids import new_ulid

OWNER_ACADEMY_ROLE: Role = "admin"
#: Body of the placeholder waiver every bootstrapped academy starts with. The
#: admin setup checklist (roadmap L7) treats a waiver still carrying exactly
#: this text as "not done yet", so keep it the single source.
DEFAULT_WAIVER_BODY = (
    "Default academy participation waiver. Replace this template before "
    "accepting student registrations."
)

DEFAULT_RECORDS = (
    "academy",
    "owner_user",
    "owner_membership",
    "waiver_template",
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
    async def ensure_waiver_template(self, waiver: dict[str, Any]) -> dict[str, Any]: ...


class InvoicePrefixAssigner(Protocol):
    """Gives a new academy its invoice-number prefix (billing owns the rules).

    Wired in composition to billing's ``AssignInvoicePrefix``, which derives
    the prefix from the slug (``ace-badminton`` -> ``ACE``), keeps it unique
    across academies, and returns the existing one on a re-bootstrap.
    """

    async def execute(self, *, academy_id: str, slug: str) -> str: ...


class BootstrapAcademyCommand(BaseModel):
    display_name: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    primary_domain: str = Field(min_length=1)
    owner_email: EmailStr
    owner_display_name: str = Field(min_length=1)
    # Required, not defaulted. A tenant created with a placeholder zone
    # makes every downstream 'resolve the timezone from the tenant' lookup
    # faithfully return the wrong answer.
    timezone: str = Field(min_length=1)
    # Platform-set, not tenant-editable. Every academy bootstrapped so far
    # (including BLNO) is badminton, so the default is today's behaviour.
    sport: str = Field(default="badminton", min_length=1)

    @field_validator("display_name", "owner_display_name", "timezone", "sport")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("timezone")
    @classmethod
    def _validate_iana_timezone(cls, value: str) -> str:
        name = value.strip()
        try:
            ZoneInfo(name)
        except (KeyError, ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError(f"'{name}' is not a known IANA timezone name") from exc
        return name

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
    #: ``None`` only when no assigner is wired (tests, legacy fixtures).
    invoice_prefix: str | None = None


class BootstrapAcademy:
    def __init__(
        self,
        *,
        store: TenantBootstrapStore,
        id_factory: Callable[[str], str] | None = None,
        clock: Callable[[], datetime] | None = None,
        invoice_prefix_assigner: InvoicePrefixAssigner | None = None,
    ) -> None:
        self._store = store
        self._invoice_prefix_assigner = invoice_prefix_assigner
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
            "sport": command.sport,
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
        await self._store.ensure_waiver_template(_default_waiver(academy_id, now, self._id_factory))

        invoice_prefix = None
        if self._invoice_prefix_assigner is not None:
            invoice_prefix = await self._invoice_prefix_assigner.execute(
                academy_id=academy_id, slug=str(academy["slug"])
            )

        return BootstrapAcademyResult(
            academy_id=academy_id,
            slug=str(academy["slug"]),
            primary_domain=str(academy["primary_domain"]),
            owner_user_id=owner_user_id,
            membership_id=str(membership["membership_id"]),
            owner_role=OWNER_ACADEMY_ROLE,
            created=created,
            invoice_prefix=invoice_prefix,
        )


def _default_waiver(
    academy_id: str,
    now: datetime,
    id_factory: Callable[[str], str],
) -> dict[str, Any]:
    text = DEFAULT_WAIVER_BODY
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


