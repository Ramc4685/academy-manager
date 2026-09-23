"""The public-page fields on ``sessions`` rows (public tenant page, Lane B1).

Enrollment is the sole writer of ``sessions``. These fields are written ONLY
here, by targeted ``$set``/``$unset`` on the named keys, so they never ride a
``Session`` round-trip (``MongoSessionWriter.update`` sets every ``Session``
field and knows nothing of these, which is exactly what keeps an ordinary
class edit from resetting a publish switch).

Reads are tolerant: a legacy row has none of these keys and reads as private,
coach shown in full, academy price period, no program. A stored value that
no longer validates reads as its default rather than failing the page.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, get_args

from pydantic import ValidationError

from backend.v2.contexts.enrollment.domain.programs import (
    DEFAULT_COACH_DISPLAY,
    AgeBand,
    ClassPublicProfile,
    CoachDisplay,
    PricePeriod,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import (
    _session_filter,
)
from backend.v2.shared.tenancy import TenantScopedRepository

#: The session-document keys this repository owns.
CLASS_PUBLIC_KEYS = (
    "program_id",
    "published",
    "price_period",
    "coach_display",
    "public_description",
    "level",
    "age_band",
)

#: Classes the public page never lists, whatever their switch says.
_NOT_LISTABLE_STATUSES = ["cancelled", "completed"]


def class_public_profile_from_doc(doc: Mapping[str, Any]) -> ClassPublicProfile:
    price_period = doc.get("price_period")
    coach_display = doc.get("coach_display")
    return ClassPublicProfile(
        session_id=str(doc.get("session_id") or doc.get("_id")),
        title=_text(doc.get("title"), 200),
        status=_text(doc.get("status"), 40),
        program_id=_text(doc.get("program_id"), 64),
        # Only a stored literal True publishes: a missing key, null, or a
        # hand-written "true" string all read as private.
        published=doc.get("published") is True,
        price_period=price_period if price_period in get_args(PricePeriod) else None,
        coach_display=(
            coach_display if coach_display in get_args(CoachDisplay) else DEFAULT_COACH_DISPLAY
        ),
        public_description=_text(doc.get("public_description"), 500),
        level=_text(doc.get("level"), 40),
        age_band=_age_band(doc.get("age_band")),
    )


class MongoClassPublicProfileRepository(TenantScopedRepository):
    collection_name = "sessions"

    async def get(self, session_id: str) -> ClassPublicProfile | None:
        doc = await self._find_one(_session_filter(session_id))
        return class_public_profile_from_doc(doc) if doc else None

    async def list_all(self, *, published_only: bool = False) -> list[ClassPublicProfile]:
        query: dict[str, Any] = {}
        if published_only:
            query = {"published": True, "status": {"$nin": _NOT_LISTABLE_STATUSES}}
        cursor = self._find_many(query)
        return [class_public_profile_from_doc(doc) async for doc in cursor]

    async def set_fields(
        self, session_id: str, fields: Mapping[str, Any]
    ) -> ClassPublicProfile | None:
        unknown = set(fields) - set(CLASS_PUBLIC_KEYS)
        if unknown:  # pragma: no cover - the use cases allow-list first
            raise ValueError(f"not a class public field: {sorted(unknown)}")
        to_set = {k: v for k, v in fields.items() if v is not None}
        to_unset = {k: "" for k, v in fields.items() if v is None}
        if not to_set and not to_unset:
            return await self.get(session_id)
        update: dict[str, Any] = {}
        if to_set:
            update["$set"] = to_set
        if to_unset:
            update["$unset"] = to_unset
        stored = await self._find_one_and_update(_session_filter(session_id), update)
        return class_public_profile_from_doc(stored) if stored else None


def _text(value: object, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] or None


def _age_band(value: object) -> AgeBand | None:
    if not isinstance(value, dict):
        return None
    try:
        return AgeBand(min_age=value.get("min_age"), max_age=value.get("max_age"))
    except ValidationError:
        return None
