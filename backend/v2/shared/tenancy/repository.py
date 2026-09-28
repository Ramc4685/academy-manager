"""TenantScopedRepository — base class that enforces tenant scoping.

All Mongo repositories in `contexts/*/infrastructure/` extend this. The base
class injects `academy_id` from the tenant ContextVar into every query and
every inserted document. Application code never references academy_id
directly.

See ADR-0006.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClientSession, AsyncIOMotorCollection

from .context import current_academy_id


class TenantScopedRepository:
    """Base class for Mongo-backed repositories.

    Subclasses set ``collection_name`` and accept a Motor database in __init__.
    Use the helper methods (``_find_one``, ``_find_many``, ``_insert_one``,
    ``_update_one``, ``_delete_one``) which thread ``academy_id`` automatically.
    """

    collection_name: str

    def __init__(self, db: Any) -> None:  # AsyncIOMotorDatabase
        self._db = db
        self.collection: AsyncIOMotorCollection = db[self.collection_name]

    # --- internal helpers ---

    @staticmethod
    def _scoped(filter_: Mapping[str, Any] | None) -> dict[str, Any]:
        scope: dict[str, Any] = dict(filter_ or {})
        scope["academy_id"] = current_academy_id()
        return scope

    @staticmethod
    def _scope_document(doc: Mapping[str, Any]) -> dict[str, Any]:
        scoped: dict[str, Any] = dict(doc)
        scoped["academy_id"] = current_academy_id()
        return scoped

    @staticmethod
    def _scope_update(update: Mapping[str, Any]) -> Mapping[str, Any]:
        """Re-stamp any ``academy_id`` an update body tries to write.

        ``_insert_one`` already overwrites a document's ``academy_id`` with the
        tenant in scope; an upsert's ``$setOnInsert`` (or a ``$set``) body is
        the same write by another route. Repositories often dump a whole domain
        object into it, and a domain object built from a boot-time academy id
        would otherwise land the row in the wrong tenant (P1 hardcoded #1: the
        scheduled pause-resume row). Pipeline updates (lists) pass through.
        """
        if not isinstance(update, Mapping):
            return update
        scoped: dict[str, Any] = dict(update)
        for operator in ("$set", "$setOnInsert"):
            body = scoped.get(operator)
            if isinstance(body, Mapping) and "academy_id" in body:
                stamped = dict(body)
                stamped["academy_id"] = current_academy_id()
                scoped[operator] = stamped
        return scoped

    # --- query helpers ---

    async def _find_one(
        self,
        filter_: Mapping[str, Any] | None = None,
        *,
        session: AsyncIOMotorClientSession | None = None,
    ) -> dict[str, Any] | None:
        return await self.collection.find_one(self._scoped(filter_), session=session)

    def _find_many(
        self,
        filter_: Mapping[str, Any] | None = None,
        *,
        sort: list[tuple[str, int]] | None = None,
        limit: int | None = None,
    ):
        cursor = self.collection.find(self._scoped(filter_))
        if sort:
            cursor = cursor.sort(sort)
        if limit:
            cursor = cursor.limit(limit)
        return cursor

    def _find_many_in_collection(
        self,
        collection_name: str,
        filter_: Mapping[str, Any] | None = None,
        projection: Mapping[str, Any] | None = None,
        *,
        sort: list[tuple[str, int]] | None = None,
        limit: int | None = None,
    ):
        cursor = self._db[collection_name].find(self._scoped(filter_), projection)
        if sort:
            cursor = cursor.sort(sort)
        if limit:
            cursor = cursor.limit(limit)
        return cursor

    async def _find_one_in_collection(
        self,
        collection_name: str,
        filter_: Mapping[str, Any] | None = None,
        *,
        sort: list[tuple[str, int]] | None = None,
        session: AsyncIOMotorClientSession | None = None,
    ) -> dict[str, Any] | None:
        return await self._db[collection_name].find_one(
            self._scoped(filter_),
            sort=sort,
            session=session,
        )

    async def _insert_one(
        self,
        doc: Mapping[str, Any],
        *,
        session: AsyncIOMotorClientSession | None = None,
    ):
        return await self.collection.insert_one(self._scope_document(doc), session=session)

    async def _update_one(
        self,
        filter_: Mapping[str, Any],
        update: Mapping[str, Any],
        *,
        upsert: bool = False,
        session: AsyncIOMotorClientSession | None = None,
    ):
        return await self.collection.update_one(
            self._scoped(filter_), self._scope_update(update), upsert=upsert, session=session
        )

    async def _find_one_and_update(
        self,
        filter_: Mapping[str, Any],
        update: Mapping[str, Any],
        *,
        upsert: bool = False,
        return_document_after: bool = True,
        session: AsyncIOMotorClientSession | None = None,
    ) -> dict[str, Any] | None:
        from pymongo import ReturnDocument

        return await self.collection.find_one_and_update(
            self._scoped(filter_),
            self._scope_update(update),
            upsert=upsert,
            return_document=(
                ReturnDocument.AFTER if return_document_after else ReturnDocument.BEFORE
            ),
            session=session,
        )

    async def _delete_one(
        self,
        filter_: Mapping[str, Any],
        *,
        session: AsyncIOMotorClientSession | None = None,
    ):
        return await self.collection.delete_one(self._scoped(filter_), session=session)

    async def _count(self, filter_: Mapping[str, Any] | None = None) -> int:
        return await self.collection.count_documents(self._scoped(filter_))
