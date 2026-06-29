"""Regression: resolving the default curriculum program must not leak raw
internal exception text to the client.

Both the coach and parent progress routes previously did
``raise HTTPException(status_code=..., detail=str(exc))`` inside a bare
``except Exception``. An unexpected error (e.g. a database failure) therefore
surfaced its raw message — and any internal identifiers it carried — to the
user. The fix keeps curated domain errors (which carry their own
``status_code``) but returns a generic 503 for anything unexpected.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.v2.interfaces.coach.skill_routes import (
    _resolve_program_id as coach_resolve,
)
from backend.v2.interfaces.parent.progress_skill_routes import (
    _resolve_program_id as parent_resolve,
)


class _Raises:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def execute(self) -> object:
        raise self._exc


def _use_cases_with(exc: Exception) -> SimpleNamespace:
    return SimpleNamespace(curriculum=SimpleNamespace(resolve_default_program=_Raises(exc)))


class _DomainError(Exception):
    """A curated domain error that carries its own status code and safe text."""

    status_code = 409

    def __init__(self) -> None:
        super().__init__("Curriculum has not been seeded for this academy.")


@pytest.mark.parametrize("resolve", [coach_resolve, parent_resolve])
@pytest.mark.asyncio
async def test_unexpected_error_is_not_leaked(resolve):
    secret = "MongoError: connection to internal-host:27017 failed (db=tenant_42)"
    with pytest.raises(HTTPException) as caught:
        await resolve(_use_cases_with(RuntimeError(secret)), None)

    assert caught.value.status_code == 503
    assert secret not in caught.value.detail
    assert "Mongo" not in caught.value.detail
    assert "27017" not in caught.value.detail
    assert "temporarily unavailable" in caught.value.detail.lower()


@pytest.mark.parametrize("resolve", [coach_resolve, parent_resolve])
@pytest.mark.asyncio
async def test_curated_domain_error_is_preserved(resolve):
    with pytest.raises(HTTPException) as caught:
        await resolve(_use_cases_with(_DomainError()), None)

    assert caught.value.status_code == 409
    assert caught.value.detail == "Curriculum has not been seeded for this academy."
