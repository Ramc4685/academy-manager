"""Read and write the academy's offline payment methods.

``GetAcademyPaymentMethods`` answers with the effective list (see
``domain/manual_payment_methods.py``: all six until the owner saves a choice).
``SetAcademyPaymentMethods`` stores the owner's choice with the marker that
makes it count. The owner gate and the audit trail sit with the caller
(billing's ``UpdateManualPaymentMethods``); this module only owns the stored
field on the academy record, one academy at a time.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any, Protocol

from backend.v2.contexts.identity.domain.manual_payment_methods import (
    MANUAL_METHODS_FIELD,
    MANUAL_METHODS_UPDATED_AT_FIELD,
    MANUAL_METHODS_UPDATED_BY_FIELD,
    effective_manual_methods,
    normalize_manual_methods,
)


class AcademyPaymentMethodsRepo(Protocol):
    async def find_by_id(self, academy_id: str) -> dict[str, Any] | None: ...

    async def update_by_id(
        self, academy_id: str, fields: dict[str, Any]
    ) -> dict[str, Any] | None: ...

    async def upsert_defaults(self, academy_id: str) -> dict[str, Any]: ...


class GetAcademyPaymentMethods:
    def __init__(self, academy_repo: AcademyPaymentMethodsRepo) -> None:
        self._repo = academy_repo

    async def execute(self, academy_id: str) -> list[str]:
        return effective_manual_methods(await self._repo.find_by_id(academy_id))


class SetAcademyPaymentMethods:
    def __init__(
        self,
        academy_repo: AcademyPaymentMethodsRepo,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repo = academy_repo
        self._now = clock

    async def execute(self, academy_id: str, methods: Iterable[Any], *, actor_id: str) -> list[str]:
        patch = {
            MANUAL_METHODS_FIELD: normalize_manual_methods(methods),
            MANUAL_METHODS_UPDATED_AT_FIELD: self._now(),
            MANUAL_METHODS_UPDATED_BY_FIELD: actor_id,
        }
        stored = await self._repo.update_by_id(academy_id, patch)
        if stored is None:
            # No academy row yet (fresh local DB): create it, then apply.
            await self._repo.upsert_defaults(academy_id)
            stored = await self._repo.update_by_id(academy_id, patch)
        if stored is None:
            raise LookupError(f"academy {academy_id} not found")
        return effective_manual_methods(stored)
