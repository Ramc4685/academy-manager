"""Read and write the academy's public page settings (Lane B1).

``GetPublicPageSettings`` always answers with the full settings, defaults
merged in (see ``domain/public_page.py``): no backfill is needed for the
academy already in production. ``UpdatePublicPageSettings`` is a partial
update: only the keys the caller sends are written, each as a dotted
``$set`` (``public_page.show_price``), so saving one switch can never reset
another. Consumers: the admin settings panel (B5) and the public read (B2).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import ValidationError

from backend.v2.contexts.identity.domain.errors import InvalidPublicPageSettings
from backend.v2.contexts.identity.domain.public_page import (
    PUBLIC_PAGE_FIELD,
    CoachProfile,
    PublicPageSettings,
)

__all__ = [
    "CoachProfile",
    "CoachRoster",
    "GetPublicPageAddress",
    "GetPublicPageSettings",
    "PublicPageSettings",
    "UpdatePublicPageSettings",
]


class AcademyPublicPageRepo(Protocol):
    async def find_by_id(self, academy_id: str) -> dict[str, Any] | None: ...

    async def update_by_id(
        self, academy_id: str, fields: dict[str, Any]
    ) -> dict[str, Any] | None: ...

    async def upsert_defaults(self, academy_id: str) -> dict[str, Any]: ...


class GetPublicPageSettings:
    def __init__(self, academy_repo: AcademyPublicPageRepo) -> None:
        self._repo = academy_repo

    async def execute(self, academy_id: str) -> PublicPageSettings:
        doc = await self._repo.find_by_id(academy_id)
        return PublicPageSettings.from_stored((doc or {}).get(PUBLIC_PAGE_FIELD))


#: A bare DNS host name (no scheme, path, port or credentials).
_HOST_RE = re.compile(
    r"^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$"
)

_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)


def _bare_host(raw: str) -> str | None:
    """The host name in ``raw``, or None.

    Accepts a bare host (``riverside.example``) or the same host written as
    a site root URL (``https://riverside.example/``); anything with a path,
    port, credentials or another scheme is refused.
    """
    value = _SCHEME_RE.sub("", raw.strip(), count=1)
    if value.endswith("/"):
        value = value[:-1]
    host = value.lower().rstrip(".")
    return host if _HOST_RE.match(host) else None


class GetPublicPageAddress:
    """The academy's own web address, for the admin panel's "View page" link.

    ``primary_domain`` (then the mirrored ``custom_domain``) on the academy
    record. ``None`` when neither is set or the stored value is not a bare
    host name: the panel then says the address is not set up yet instead of
    guessing (in production the admin app runs on the product host, whose
    ``/`` is the CourtMastr landing page, not the academy's page).
    """

    def __init__(self, academy_repo: AcademyPublicPageRepo) -> None:
        self._repo = academy_repo

    async def execute(self, academy_id: str) -> str | None:
        doc = await self._repo.find_by_id(academy_id) or {}
        for key in ("primary_domain", "custom_domain"):
            raw = doc.get(key)
            if isinstance(raw, str):
                host = _bare_host(raw)
                if host is not None:
                    return f"https://{host}/"
        return None


class CoachRoster(Protocol):
    async def coach_ids(self, academy_id: str, candidate_ids: list[str]) -> set[str]:
        """The subset of ``candidate_ids`` that hold an active coach (or
        assistant coach) membership in ``academy_id``."""
        ...


class UpdatePublicPageSettings:
    def __init__(
        self,
        academy_repo: AcademyPublicPageRepo,
        coach_roster: CoachRoster | None = None,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repo = academy_repo
        self._coaches = coach_roster
        self._now = now or (lambda: datetime.now(UTC))

    async def execute(
        self,
        academy_id: str,
        fields: Mapping[str, Any],
        *,
        actor_id: str | None = None,
    ) -> PublicPageSettings:
        unknown = sorted(set(fields) - set(PublicPageSettings.model_fields))
        if unknown:
            raise InvalidPublicPageSettings("Unknown public page setting.", fields=unknown)
        _reject_coerced_booleans(fields)
        doc = await self._repo.find_by_id(academy_id)
        current = PublicPageSettings.from_stored((doc or {}).get(PUBLIC_PAGE_FIELD))
        fields = dict(fields)
        if "gallery" in fields:
            fields["gallery"] = self._stamp_gallery(fields["gallery"], current, actor_id)
        if "coach_profiles" in fields:
            await self._check_coach_profiles(academy_id, fields["coach_profiles"])
        try:
            merged = PublicPageSettings.model_validate(
                {**current.model_dump(), **fields}, strict=False
            )
        except ValidationError as exc:
            bad = sorted({str(err["loc"][0]) for err in exc.errors() if err.get("loc")})
            raise InvalidPublicPageSettings(
                "Public page settings are not valid.", fields=bad
            ) from exc
        if not fields:
            return current
        # Plain dicts, never model instances, so nested lists store as documents.
        dumped = merged.model_dump()
        patch = {f"{PUBLIC_PAGE_FIELD}.{key}": dumped[key] for key in fields}
        stored = await self._repo.update_by_id(academy_id, patch)
        if stored is None:
            # No academy row yet (fresh local DB): create the defaults row,
            # then apply the patch to it.
            await self._repo.upsert_defaults(academy_id)
            stored = await self._repo.update_by_id(academy_id, patch)
        if stored is None:
            raise LookupError(f"academy {academy_id} not found")
        return PublicPageSettings.from_stored(stored.get(PUBLIC_PAGE_FIELD))

    def _stamp_gallery(
        self, raw: object, current: PublicPageSettings, actor_id: str | None
    ) -> list[dict[str, Any]]:
        """Server-stamp consent on each item; refuse any without consent.

        The client sends ``{url, caption, consent_confirmed}``. A photo already
        in the saved gallery keeps its original stamp (who confirmed, when);
        a new one is stamped with the caller and now. Client-supplied stamps
        are ignored.
        """
        if not isinstance(raw, list) or not all(isinstance(item, Mapping) for item in raw):
            raise InvalidPublicPageSettings("Gallery is not valid.", fields=["gallery"])
        existing = {photo.url: photo for photo in current.gallery}
        stamped: list[dict[str, Any]] = []
        now = self._now()
        for item in raw:
            if item.get("consent_confirmed") is not True:
                raise InvalidPublicPageSettings(
                    "Confirm that parents or guardians agreed to each gallery photo "
                    "being published.",
                    fields=["gallery"],
                )
            url = str(item.get("url") or "").strip()
            kept = existing.get(url)
            stamped.append(
                {
                    "url": url,
                    "caption": item.get("caption") or "",
                    "consent_confirmed": True,
                    "consent_confirmed_by": kept.consent_confirmed_by
                    if kept
                    else (actor_id or "unknown"),
                    "consent_confirmed_at": kept.consent_confirmed_at if kept else now,
                }
            )
        return stamped

    async def _check_coach_profiles(self, academy_id: str, raw: object) -> None:
        if not isinstance(raw, list) or not all(isinstance(item, Mapping) for item in raw):
            raise InvalidPublicPageSettings(
                "Coach profiles are not valid.", fields=["coach_profiles"]
            )
        if any(not isinstance(item.get("shown", True), bool) for item in raw):
            raise InvalidPublicPageSettings(
                "Public page switches must be true or false.", fields=["coach_profiles"]
            )
        ids = [str(item.get("coach_id") or "").strip() for item in raw]
        if len(set(ids)) != len(ids):
            raise InvalidPublicPageSettings(
                "Each coach can have one profile.", fields=["coach_profiles"]
            )
        if not ids:
            return
        allowed = (
            await self._coaches.coach_ids(academy_id, ids) if self._coaches is not None else set()
        )
        if not set(ids) <= allowed:
            raise InvalidPublicPageSettings(
                "Coach profiles can only be set for coaches of this academy.",
                fields=["coach_profiles"],
            )


_BOOL_KEYS = ("published", "show_price", "show_availability", "trials_open")


def _reject_coerced_booleans(fields: Mapping[str, Any]) -> None:
    """Pydantic lax mode turns ``"no"`` or ``0`` into ``False``; a switch
    that publishes a page must be a real boolean, never a coerced string."""
    bad = sorted(k for k in _BOOL_KEYS if k in fields and not isinstance(fields[k], bool))
    if bad:
        raise InvalidPublicPageSettings("Public page switches must be true or false.", fields=bad)
