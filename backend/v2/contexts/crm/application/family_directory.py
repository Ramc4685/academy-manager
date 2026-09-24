"""``FamilyDirectory`` over the family index: the one "is this a family here" check.

Notes and follow-ups attach to a family by its canonical parent id. The same
index that backs ``/admin/families`` and the family record page decides
whether an id is a family of the caller's academy (tenant membership alone is
not enough, #664: a parent of academy B is not a family of academy A), and
resolves an alias URL to the canonical id so every note lands on one key.

The index is cached for a minute (spec §3.2). A family created inside that
minute is not in the cached copy yet, so a miss is re-checked once against a
fresh build before it becomes a 404.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from backend.v2.contexts.crm.application.family_index import FamilyIndex, find_family_record
from backend.v2.contexts.crm.application.ports import FamilyRef


class _IndexBuilder(Protocol):
    async def build(self, academy_id: str) -> FamilyIndex: ...


class IndexFamilyDirectory:
    def __init__(self, cached: _IndexBuilder, fresh: _IndexBuilder) -> None:
        self._cached = cached
        self._fresh = fresh

    async def find(self, academy_id: str, family_id: str) -> FamilyRef | None:
        record = find_family_record(await self._cached.build(academy_id), family_id)
        if record is None:
            record = find_family_record(await self._fresh.build(academy_id), family_id)
        return record

    async def names(self, academy_id: str) -> Mapping[str, str | None]:
        index = await self._cached.build(academy_id)
        return {record.family_id: record.parent_name for record in index.families}
