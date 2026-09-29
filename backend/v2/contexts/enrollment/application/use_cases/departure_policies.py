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
    """The Holds card's three mutable fields, plus ``drop_default_outcome``.

    ``drop_default_outcome`` moved to Settings -> Billing rules (Settings
    overhaul Phase 3 PR 10, same pattern PR #1002 used for the cancellation
    fee/notice): it is optional here and written only by the Billing rules
    adapter in ``composition/billing_rules.py``. The Holds route
    (``interfaces/admin/departure_policy_routes.py``) never passes it, so a
    save from the Holds card cannot put back a stale drop-outcome value.
    Every field is optional so either caller can send a partial update.
    """

    max_hold_days: int | None = Field(default=None, ge=1, le=365)
    hold_reclaim_policy: Literal["longest_held", "never"] | None = None
    drop_default_outcome: (
        Literal["no_credit_mid_month", "credit_mid_month", "no_credit_end_of_period"] | None
    ) = None
    delete_enrollment_requires_owner: bool | None = None


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
        updates = cmd.model_dump(exclude_none=True)
        if not updates:
            return current
        updated = current.model_copy(update=updates)
        await self._policies.save(updated)
        return updated
