"""Admin "Delivery problems" (L11 item 3): the academy sees suppressed
addresses and failed campaign sends for its own people only, and may clear a
hard bounce, never a spam complaint, and never another academy's address."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.communications.application.ports import ResolvedRecipient
from backend.v2.contexts.communications.application.use_cases.delivery_problems import (
    GetDeliveryProblems,
    NotAMember,
    NotReleasable,
    ReleaseMemberSuppression,
)
from backend.v2.contexts.communications.domain.email_suppression import (
    EmailSuppression,
    SuppressionReason,
)
from backend.v2.contexts.communications.domain.models import (
    AcademyAudience,
    Delivery,
    DeliveryStatus,
)

T = datetime(2026, 11, 1, tzinfo=UTC)


class _Resolver:
    async def resolve_academy_audience(self, audience: AcademyAudience) -> list[ResolvedRecipient]:
        return {
            "parent": [
                ResolvedRecipient(user_id="p1", email="Bounce@Example.test"),
                ResolvedRecipient(user_id="p2", email="spam@example.test"),
                ResolvedRecipient(user_id="p3", email=None),
            ],
            "coach": [ResolvedRecipient(user_id="c1", email="coach@example.test")],
        }.get(audience.role, [])


def _sup(email: str, reason: SuppressionReason) -> EmailSuppression:
    return EmailSuppression(email=email, reason=reason, first_seen_at=T, last_seen_at=T)


class _Suppressions:
    def __init__(self) -> None:
        self.rows = {
            "bounce@example.test": _sup("bounce@example.test", SuppressionReason.HARD_BOUNCE),
            "spam@example.test": _sup("spam@example.test", SuppressionReason.COMPLAINT),
            "other-academy@example.test": _sup(
                "other-academy@example.test", SuppressionReason.HARD_BOUNCE
            ),
        }
        self.released: list[str] = []

    async def list_active_for(self, emails: list[str]) -> list[EmailSuppression]:
        return [self.rows[e] for e in emails if e in self.rows]

    async def get_active(self, email: str) -> EmailSuppression | None:
        return self.rows.get(email.lower())

    async def release(self, *, email: str, released_by: str) -> bool:
        self.released.append(email)
        return True


class _Deliveries:
    async def list_failed(self, *, limit: int) -> list[Delivery]:
        return [
            Delivery(
                delivery_id="d1",
                academy_id="acad",
                campaign_id="c1",
                recipient_user_id="p1",
                recipient_email="bounce@example.test",
                status=DeliveryStatus.FAILED,
                provider_message_id=None,
                sent_at=None,
                opened_at=None,
                failed_reason="provider 422",
            )
        ][:limit]


async def test_lists_only_this_academys_suppressed_people_and_failed_sends() -> None:
    result = await GetDeliveryProblems(
        resolver=_Resolver(),  # type: ignore[arg-type]
        suppressions=_Suppressions(),  # type: ignore[arg-type]
        deliveries=_Deliveries(),  # type: ignore[arg-type]
        release_enabled=True,
    ).execute()
    by_email = {row.email: row for row in result.suppressed}
    assert set(by_email) == {"bounce@example.test", "spam@example.test"}
    assert by_email["bounce@example.test"].user_id == "p1"
    assert by_email["bounce@example.test"].releasable is True
    assert by_email["spam@example.test"].releasable is False
    assert [d.delivery_id for d in result.failed] == ["d1"]


async def test_nothing_is_releasable_while_the_setting_is_off() -> None:
    result = await GetDeliveryProblems(
        resolver=_Resolver(),  # type: ignore[arg-type]
        suppressions=_Suppressions(),  # type: ignore[arg-type]
        deliveries=_Deliveries(),  # type: ignore[arg-type]
        release_enabled=False,
    ).execute()
    assert not any(row.releasable for row in result.suppressed)


def _release(store: _Suppressions, *, enabled: bool = True) -> ReleaseMemberSuppression:
    return ReleaseMemberSuppression(
        resolver=_Resolver(),  # type: ignore[arg-type]
        suppressions=store,  # type: ignore[arg-type]
        release_enabled=enabled,
    )


async def test_releases_a_members_hard_bounce() -> None:
    store = _Suppressions()
    assert await _release(store).execute(email="BOUNCE@example.test", released_by="admin") is True
    assert store.released == ["bounce@example.test"]


@pytest.mark.parametrize(
    ("email", "error"),
    [
        ("spam@example.test", NotReleasable),
        ("other-academy@example.test", NotAMember),
    ],
)
async def test_never_releases_a_complaint_or_another_academys_address(
    email: str, error: type[Exception]
) -> None:
    store = _Suppressions()
    with pytest.raises(error):
        await _release(store).execute(email=email, released_by="admin")
    assert store.released == []


async def test_release_is_refused_while_the_setting_is_off() -> None:
    store = _Suppressions()
    with pytest.raises(NotReleasable):
        await _release(store, enabled=False).execute(
            email="bounce@example.test", released_by="admin"
        )
    assert store.released == []
