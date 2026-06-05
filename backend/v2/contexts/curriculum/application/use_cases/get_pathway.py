"""Curriculum use cases: full pathway read."""

from __future__ import annotations

from backend.v2.contexts.curriculum.application.ports import PathwayQuery
from backend.v2.contexts.curriculum.domain.errors import ProgramNotFound
from backend.v2.contexts.curriculum.domain.models import FullPathway


class GetFullPathway:
    def __init__(self, *, pathway_query: PathwayQuery) -> None:
        self._query = pathway_query

    async def execute(self, program_id: str) -> FullPathway:
        pathway = await self._query.get_full_pathway(program_id)
        if pathway is None:
            raise ProgramNotFound("program not found", program_id=program_id)
        return pathway
