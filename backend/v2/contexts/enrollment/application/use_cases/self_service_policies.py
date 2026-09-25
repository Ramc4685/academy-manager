"""Read/update the per-academy parent self-service policy.

Used by the admin BFF (get + update) and, in later tasks, by parent-facing
reads. The repo is injected as a Protocol so unit tests can use an in-memory
fake instead of Mongo.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from backend.v2.contexts.enrollment.domain.self_service import ParentSelfServicePolicy


class SelfServicePolicyRepo(Protocol):
    async def get_or_default(self) -> ParentSelfServicePolicy: ...
    async def save(self, policy: ParentSelfServicePolicy) -> None: ...
    async def update_fields(self, fields: dict[str, Any]) -> None:
        """``$set`` exactly these fields; leave every other stored value alone."""
        ...


class UpdateSelfServicePolicyCommand(BaseModel):
    """Any of the six mutable fields of ParentSelfServicePolicy.

    Every field is optional and only the ones present are written (money
    audit X5, 2026-09-25). Two Settings panels write this one document: the
    Self-service tab owns four fields and Billing rules owns the two
    cancellation fields. A whole-object write from either one put back
    whatever the other had just saved.
    """

    absence_notice_min_hours: int | None = Field(default=None, ge=0)
    #: At least 1: ``RequestMakeup`` refuses any request after
    #: ``missed start + makeup_expiry_days``, so 0 rejects every makeup (X20).
    makeup_expiry_days: int | None = Field(default=None, ge=1)
    makeup_requires_notice: bool | None = None
    cancellation_minimum_notice_days: int | None = Field(default=None, ge=0)
    cancellation_fee_cents: int | None = Field(default=None, ge=0)
    cancellation_effective_timing: Literal["immediate", "end_of_period"] | None = None

    def fields(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class GetSelfServicePolicy:
    def __init__(self, policies: SelfServicePolicyRepo) -> None:
        self._policies = policies

    async def execute(self) -> ParentSelfServicePolicy:
        return await self._policies.get_or_default()


class UpdateSelfServicePolicy:
    def __init__(self, policies: SelfServicePolicyRepo) -> None:
        self._policies = policies

    async def execute(self, cmd: UpdateSelfServicePolicyCommand) -> ParentSelfServicePolicy:
        fields = cmd.fields()
        if fields:
            await self._policies.update_fields(fields)
        return await self._policies.get_or_default()
