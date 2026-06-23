from __future__ import annotations

import pytest

from backend.v2.contexts.billing.application.use_cases.tuition_discounts import (
    RemoveTuitionDiscount,
    RemoveTuitionDiscountCommand,
    SetTuitionDiscount,
    SetTuitionDiscountCommand,
)
from backend.v2.contexts.billing.domain.tuition_discount import TuitionDiscount


class _FakeRepo:
    def __init__(self) -> None:
        self.set_calls: list[tuple[TuitionDiscount, str]] = []
        self.removed: list[tuple[str, str]] = []

    async def set_active(self, policy: TuitionDiscount, *, set_by: str) -> TuitionDiscount:
        self.set_calls.append((policy, set_by))
        return policy

    async def remove(self, enrollment_id: str, *, ended_by: str) -> None:
        self.removed.append((enrollment_id, ended_by))


@pytest.mark.asyncio
async def test_set_builds_policy_and_persists() -> None:
    repo = _FakeRepo()
    await SetTuitionDiscount(discounts=repo).execute(
        SetTuitionDiscountCommand(
            discount_id="disc-1",
            enrollment_id="enroll-1",
            student_id="student-1",
            category="sibling",
            kind="percent",
            percent_bps=1000,
            effective_start="2026-06-01",
            set_by="admin-1",
        )
    )
    assert len(repo.set_calls) == 1
    policy, set_by = repo.set_calls[0]
    assert policy.category == "sibling"
    assert policy.percent_bps == 1000
    assert set_by == "admin-1"


@pytest.mark.asyncio
async def test_set_rejects_other_without_label() -> None:
    repo = _FakeRepo()
    with pytest.raises(ValueError):
        await SetTuitionDiscount(discounts=repo).execute(
            SetTuitionDiscountCommand(
                discount_id="disc-1",
                enrollment_id="enroll-1",
                student_id="student-1",
                category="other",
                kind="waiver",
                effective_start="2026-06-01",
                set_by="admin-1",
            )
        )


@pytest.mark.asyncio
async def test_remove_calls_repo() -> None:
    repo = _FakeRepo()
    await RemoveTuitionDiscount(discounts=repo).execute(
        RemoveTuitionDiscountCommand(enrollment_id="enroll-1", ended_by="admin-2")
    )
    assert repo.removed == [("enroll-1", "admin-2")]
