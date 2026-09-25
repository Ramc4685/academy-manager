"""Use-case tests for per-academy parent self-service policy."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.v2.contexts.enrollment.application.use_cases.self_service_policies import (
    GetSelfServicePolicy,
    UpdateSelfServicePolicy,
    UpdateSelfServicePolicyCommand,
)
from backend.v2.contexts.enrollment.domain.self_service import ParentSelfServicePolicy


class _FakeRepo:
    def __init__(self) -> None:
        self.saved: list[ParentSelfServicePolicy] = []
        self.field_writes: list[dict[str, object]] = []
        self._policy: ParentSelfServicePolicy | None = None

    async def get_or_default(self) -> ParentSelfServicePolicy:
        if self._policy is not None:
            return self._policy
        return ParentSelfServicePolicy.default("acad")

    async def save(self, policy: ParentSelfServicePolicy) -> None:
        self._policy = policy
        self.saved.append(policy)

    async def update_fields(self, fields: dict[str, object]) -> None:
        """Mirrors the Mongo repo: ``$set`` of exactly these keys, nothing else."""
        self.field_writes.append(dict(fields))
        current = await self.get_or_default()
        self._policy = current.model_copy(update=fields)


@pytest.mark.asyncio
async def test_get_returns_default_when_none_saved() -> None:
    repo = _FakeRepo()

    policy = await GetSelfServicePolicy(policies=repo).execute()

    assert policy == ParentSelfServicePolicy.default("acad")
    assert policy.absence_notice_min_hours == 2
    assert policy.makeup_expiry_days == 30
    assert policy.makeup_requires_notice is True
    assert policy.cancellation_minimum_notice_days == 7
    assert policy.cancellation_fee_cents == 0
    assert policy.cancellation_effective_timing == "end_of_period"


@pytest.mark.asyncio
async def test_update_persists_and_returns_new_policy() -> None:
    repo = _FakeRepo()

    result = await UpdateSelfServicePolicy(policies=repo).execute(
        UpdateSelfServicePolicyCommand(
            absence_notice_min_hours=4,
            makeup_expiry_days=45,
            makeup_requires_notice=False,
            cancellation_minimum_notice_days=14,
            cancellation_fee_cents=2500,
            cancellation_effective_timing="immediate",
        )
    )

    assert result.absence_notice_min_hours == 4
    assert result.makeup_expiry_days == 45
    assert result.makeup_requires_notice is False
    assert result.cancellation_minimum_notice_days == 14
    assert result.cancellation_fee_cents == 2500
    assert result.cancellation_effective_timing == "immediate"
    assert len(repo.field_writes) == 1

    fetched = await GetSelfServicePolicy(policies=repo).execute()
    assert fetched.absence_notice_min_hours == 4


@pytest.mark.asyncio
async def test_update_rejects_negative_notice_hours() -> None:
    with pytest.raises(ValidationError):
        UpdateSelfServicePolicyCommand(
            absence_notice_min_hours=-1,
            makeup_expiry_days=30,
            makeup_requires_notice=True,
            cancellation_minimum_notice_days=7,
            cancellation_fee_cents=0,
            cancellation_effective_timing="end_of_period",
        )


@pytest.mark.asyncio
async def test_update_rejects_negative_makeup_expiry_days() -> None:
    with pytest.raises(ValidationError):
        UpdateSelfServicePolicyCommand(
            absence_notice_min_hours=2,
            makeup_expiry_days=-5,
            makeup_requires_notice=True,
            cancellation_minimum_notice_days=7,
            cancellation_fee_cents=0,
            cancellation_effective_timing="end_of_period",
        )


@pytest.mark.asyncio
async def test_update_rejects_negative_cancellation_notice_days() -> None:
    with pytest.raises(ValidationError):
        UpdateSelfServicePolicyCommand(
            absence_notice_min_hours=2,
            makeup_expiry_days=30,
            makeup_requires_notice=True,
            cancellation_minimum_notice_days=-1,
            cancellation_fee_cents=0,
            cancellation_effective_timing="end_of_period",
        )


@pytest.mark.asyncio
async def test_update_rejects_negative_cancellation_fee_cents() -> None:
    with pytest.raises(ValidationError):
        UpdateSelfServicePolicyCommand(
            absence_notice_min_hours=2,
            makeup_expiry_days=30,
            makeup_requires_notice=True,
            cancellation_minimum_notice_days=7,
            cancellation_fee_cents=-100,
            cancellation_effective_timing="end_of_period",
        )


# --- Partial writes (money audit X5, 2026-09-25) -----------------------------


@pytest.mark.asyncio
async def test_update_writes_only_the_fields_it_was_given() -> None:
    """The write used to ``$set`` all six fields from the caller's copy.

    The Settings page caches the policy for minutes, so saving an absence
    setting from a stale Self-service tab silently put back an older
    cancellation fee that the owner had just changed in Billing rules.
    """
    repo = _FakeRepo()
    await repo.update_fields({"cancellation_fee_cents": 2500})

    result = await UpdateSelfServicePolicy(policies=repo).execute(
        UpdateSelfServicePolicyCommand(absence_notice_min_hours=6)
    )

    assert repo.field_writes[-1] == {"absence_notice_min_hours": 6}
    assert result.absence_notice_min_hours == 6
    assert result.cancellation_fee_cents == 2500


@pytest.mark.asyncio
async def test_an_empty_update_writes_nothing() -> None:
    repo = _FakeRepo()

    await UpdateSelfServicePolicy(policies=repo).execute(UpdateSelfServicePolicyCommand())

    assert repo.field_writes == []


# --- makeup_expiry_days = 0 rejects every makeup (X20) -----------------------


def test_update_rejects_a_zero_makeup_expiry() -> None:
    """``RequestMakeup`` refuses any request past ``start + expiry days``, so 0
    closes the window at class start and every makeup request fails. A cleared
    input on the Settings page used to save exactly that."""
    with pytest.raises(ValidationError):
        UpdateSelfServicePolicyCommand(makeup_expiry_days=0)
