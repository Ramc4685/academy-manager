"""Read/update the per-academy EnrollmentDeparturePolicy (issue #697).

Structurally a copy of ``self_service_policies.py`` — same pattern, sibling
model. See ``domain/departure_policy.py`` for why this is not a shared PUT
with the self-service panel.
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field

from backend.v2.contexts.enrollment.domain.departure_policy import EnrollmentDeparturePolicy


class DeparturePolicyRepo(Protocol):
    async def get_or_default(self) -> EnrollmentDeparturePolicy: ...
    async def save(self, policy: EnrollmentDeparturePolicy) -> None: ...


class UpdateEnrollmentDeparturePolicyCommand(BaseModel):
    """The four mutable fields of EnrollmentDeparturePolicy."""

    max_hold_days: int = Field(ge=1, le=365)
    hold_reclaim_policy: Literal["longest_held", "never"]
    drop_default_outcome: Literal[
        "no_credit_mid_month", "credit_mid_month", "no_credit_end_of_period"
    ]
    delete_enrollment_requires_owner: bool


class GetEnrollmentDeparturePolicy:
    def __init__(self, policies: DeparturePolicyRepo) -> None:
        self._policies = policies

    async def execute(self) -> EnrollmentDeparturePolicy:
        return await self._policies.get_or_default()


class UpdateEnrollmentDeparturePolicy:
    def __init__(self, policies: DeparturePolicyRepo) -> None:
        self._policies = policies

    async def execute(
        self, cmd: UpdateEnrollmentDeparturePolicyCommand
    ) -> EnrollmentDeparturePolicy:
        current = await self._policies.get_or_default()
        updated = current.model_copy(
            update={
                "max_hold_days": cmd.max_hold_days,
                "hold_reclaim_policy": cmd.hold_reclaim_policy,
                "drop_default_outcome": cmd.drop_default_outcome,
                "delete_enrollment_requires_owner": cmd.delete_enrollment_requires_owner,
            }
        )
        await self._policies.save(updated)
        return updated
