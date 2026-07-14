"""Onboarding application ports."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from backend.v2.contexts.onboarding.domain.models import Application, Waiver


class ApplicationRepository(Protocol):
    async def save(self, app: Application) -> None: ...
    async def get(self, application_id: str) -> Application | None: ...
    async def latest_for_parent(self, parent_user_id: str) -> Application | None: ...
    async def get_by_payment_id(self, payment_id: str) -> Application | None: ...
    async def list_by_status(self, statuses: list[str]) -> list[Application]: ...
    async def claim_for_review(
        self,
        application_id: str,
        processing_status: str,
        *,
        claim_token: str,
        updated_at: datetime,
        stale_before: datetime,
    ) -> Application | None: ...
    async def release_review(
        self,
        application_id: str,
        processing_status: str,
        *,
        claim_token: str,
        updated_at: datetime,
    ) -> None: ...
    async def renew_review_claim(
        self, application_id: str, claim_token: str, *, claimed_at: datetime
    ) -> bool: ...
    async def complete_review(self, app: Application, *, claim_token: str) -> bool: ...


class WaiverRepository(Protocol):
    async def get_active(self) -> Waiver | None: ...
