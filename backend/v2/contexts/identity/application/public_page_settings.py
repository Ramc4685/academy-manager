"""Read and write the academy's public page settings (Lane B1).

``GetPublicPageSettings`` always answers with the full settings, defaults
merged in (see ``domain/public_page.py``): no backfill is needed for the
academy already in production. ``UpdatePublicPageSettings`` is a partial
update: only the keys the caller sends are written, each as a dotted
``$set`` (``public_page.show_price``), so saving one switch can never reset
another. Consumers: the admin settings panel (B5) and the public read (B2).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from pydantic import ValidationError

from backend.v2.contexts.identity.domain.errors import InvalidPublicPageSettings
from backend.v2.contexts.identity.domain.public_page import (
    PUBLIC_PAGE_FIELD,
    PublicPageSettings,
)

__all__ = [
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


class UpdatePublicPageSettings:
    def __init__(self, academy_repo: AcademyPublicPageRepo) -> None:
        self._repo = academy_repo

    async def execute(self, academy_id: str, fields: Mapping[str, Any]) -> PublicPageSettings:
        unknown = sorted(set(fields) - set(PublicPageSettings.model_fields))
        if unknown:
            raise InvalidPublicPageSettings("Unknown public page setting.", fields=unknown)
        _reject_coerced_booleans(fields)
        doc = await self._repo.find_by_id(academy_id)
        current = PublicPageSettings.from_stored((doc or {}).get(PUBLIC_PAGE_FIELD))
        try:
            merged = PublicPageSettings.model_validate(
                {**current.model_dump(), **dict(fields)}, strict=False
            )
        except ValidationError as exc:
            bad = sorted({str(err["loc"][0]) for err in exc.errors() if err.get("loc")})
            raise InvalidPublicPageSettings(
                "Public page settings are not valid.", fields=bad
            ) from exc
        if not fields:
            return current
        patch = {f"{PUBLIC_PAGE_FIELD}.{key}": getattr(merged, key) for key in fields}
        stored = await self._repo.update_by_id(academy_id, patch)
        if stored is None:
            # No academy row yet (fresh local DB): create the defaults row,
            # then apply the patch to it.
            await self._repo.upsert_defaults(academy_id)
            stored = await self._repo.update_by_id(academy_id, patch)
        if stored is None:
            raise LookupError(f"academy {academy_id} not found")
        return PublicPageSettings.from_stored(stored.get(PUBLIC_PAGE_FIELD))


_BOOL_KEYS = ("published", "show_price", "show_availability", "trials_open")


def _reject_coerced_booleans(fields: Mapping[str, Any]) -> None:
    """Pydantic lax mode turns ``"no"`` or ``0`` into ``False``; a switch
    that publishes a page must be a real boolean, never a coerced string."""
    bad = sorted(k for k in _BOOL_KEYS if k in fields and not isinstance(fields[k], bool))
    if bad:
        raise InvalidPublicPageSettings("Public page switches must be true or false.", fields=bad)
