"""``MongoUserRepository.resolve_parent_aliases`` (People CRM spec §1, #894).

A stored parent reference may be a roster ``user_id``, a ``firebase_uid``, an
``auth_uid`` or the users ``_id``. Resolution is one ``$in`` per field, later
fields only for ids still unresolved, and never an ``$or`` across fields.
"""

from __future__ import annotations

from typing import Any

import pytest
from bson import ObjectId

from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository

OID = ObjectId("65f0000000000000000000b1")


class _Spy:
    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.filters: list[dict[str, Any]] = []

    def find(self, flt: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        self.filters.append(flt)
        return self._inner.find(flt, *args, **kwargs)

    def __getattr__(self, attr: str) -> Any:
        return getattr(self._inner, attr)


async def _seed(db: Any) -> None:
    await db["users"].insert_many(
        [
            {"user_id": "u-roster", "firebase_uid": "fb-a", "display_name": "Testparent A"},
            {"_id": OID, "firebase_uid": "fb-b", "email": "b@example.test"},
            {"user_id": "u-c", "auth_uid": "auth-c", "roles": "parent", "academy_id": "acad-1"},
            {"_id": "legacy-string-id", "display_name": "Testparent Legacy"},
        ]
    )


@pytest.mark.asyncio
async def test_each_field_resolves_to_the_canonical_id(db) -> None:
    await _seed(db)
    repo = MongoUserRepository(db)
    spy = _Spy(repo.collection)
    repo.collection = spy  # type: ignore[assignment]

    out = await repo.resolve_parent_aliases(
        ["u-roster", "fb-a", "fb-b", str(OID), "auth-c", "legacy-string-id", "nobody", "u-roster"]
    )

    assert out["u-roster"].canonical_id == "u-roster"
    assert out["fb-a"].canonical_id == "u-roster"
    assert out["fb-a"].aliases >= {"u-roster", "fb-a"}
    assert out["fb-b"].canonical_id == str(OID)
    assert out[str(OID)].canonical_id == str(OID)
    assert out["auth-c"].canonical_id == "u-c"
    assert out["auth-c"].roles == ("parent",)
    assert out["auth-c"].home_academy_id == "acad-1"
    assert out["auth-c"].login_uid == "auth-c"
    assert out["legacy-string-id"].display_name == "Testparent Legacy"
    assert "nobody" not in out

    # One query per field, in order, never an $or; later fields only ask
    # about what is still unresolved.
    assert [next(iter(f)) for f in spy.filters] == ["user_id", "firebase_uid", "auth_uid", "_id"]
    assert all("$or" not in f for f in spy.filters)
    assert set(spy.filters[1]["firebase_uid"]["$in"]) == {
        "fb-a",
        "fb-b",
        str(OID),
        "auth-c",
        "legacy-string-id",
        "nobody",
    }
    assert "fb-a" not in spy.filters[2]["auth_uid"]["$in"]


@pytest.mark.asyncio
async def test_stops_early_when_everything_resolved(db) -> None:
    await _seed(db)
    repo = MongoUserRepository(db)
    spy = _Spy(repo.collection)
    repo.collection = spy  # type: ignore[assignment]
    await repo.resolve_parent_aliases(["u-roster", "u-c"])
    assert len(spy.filters) == 1
    assert await repo.resolve_parent_aliases([]) == {}
