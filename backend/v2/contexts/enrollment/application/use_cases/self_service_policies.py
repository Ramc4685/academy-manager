"""Read/update the per-academy parent self-service policy.

Used by the admin BFF (get + update) and, in later tasks, by parent-facing
reads. The repo is injected as a Protocol so unit tests can use an in-memory
fake instead of Mongo.
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field

from backend.v2.contexts.enrollment.domain.self_service import ParentSelfServicePolicy


class SelfServicePolicyRepo(Protocol):
    async def get_or_default(self) -> ParentSelfServicePolicy: ...
    async def save(self, policy: ParentSelfServicePolicy) -> None: ...


class UpdateSelfServicePolicyCommand(BaseModel):
    """The six mutable fields of ParentSelfServicePolicy."""

    absence_notice_min_hours: int = Field(ge=0)
    makeup_expiry_days: int = Field(ge=0)
    makeup_requires_notice: bool
    cancellation_minimum_notice_days: int = Field(ge=0)
    cancellation_fee_cents: int = Field(ge=0)
    cancellation_effective_timing: Literal["immediate", "end_of_period"]


class GetSelfServicePolicy:
    def __init__(self, policies: SelfServicePolicyRepo) -> None:
        self._policies = policies

    async def execute(self) -> ParentSelfServicePolicy:
        return await self._policies.get_or_default()


class UpdateSelfServicePolicy:
    def __init__(self, policies: SelfServicePolicyRepo) -> None:
        self._policies = policies

    async def execute(self, cmd: UpdateSelfServicePolicyCommand) -> ParentSelfServicePolicy:
        current = await self._policies.get_or_default()
        updated = current.model_copy(
            update={
                "absence_notice_min_hours": cmd.absence_notice_min_hours,
                "makeup_expiry_days": cmd.makeup_expiry_days,
                "makeup_requires_notice": cmd.makeup_requires_notice,
                "cancellation_minimum_notice_days": cmd.cancellation_minimum_notice_days,
                "cancellation_fee_cents": cmd.cancellation_fee_cents,
                "cancellation_effective_timing": cmd.cancellation_effective_timing,
            }
        )
        await self._policies.save(updated)
        return updated
