"""Compare-and-set contract for the checkout-ownership writes.

`reopen_for_edit` and `restamp_checkout` are the only writes on the checkout
path that two callers can reach at once — the wizard remounting while a
payment webhook lands, and two tabs starting checkout together. Both must MISS
rather than overwrite when the stored document no longer matches what the
caller read; a read-then-blind-write here loses a real payment.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.onboarding.domain.models import Application
from backend.v2.contexts.onboarding.infrastructure.mongo_application_repo import (
    MongoApplicationRepository,
)

NOW = datetime(2026, 7, 14, tzinfo=UTC)


def _application(acad: str, **extra) -> Application:
    return Application(
        application_id="app-1",
        academy_id=acad,
        parent_user_id="parent-1",
        parent_email="parent@example.com",
        status="CHECKOUT_PENDING",
        stripe_checkout_session_id="cs_first",
        payment_id="pay-first",
        expires_at=NOW + timedelta(days=7),
        created_at=NOW,
        updated_at=NOW,
        **extra,
    )


@pytest.mark.asyncio
async def test_reopen_for_edit_returns_a_checkout_pending_application_to_draft(db, acad) -> None:
    repo = MongoApplicationRepository(db)
    await repo.save(_application(acad))

    resumed = await repo.reopen_for_edit(
        "app-1", expected_status="CHECKOUT_PENDING", updated_at=NOW
    )

    assert resumed is not None
    assert resumed.status == "DRAFT"
    # The payment pointer stays: it is the only handle a late
    # checkout.session.completed has back to this application.
    assert resumed.payment_id == "pay-first"


@pytest.mark.asyncio
async def test_reopen_for_edit_misses_once_the_application_has_been_paid(db, acad) -> None:
    """The webhook won the race while the wizard was mounting."""
    repo = MongoApplicationRepository(db)
    await repo.save(_application(acad).model_copy(update={"status": "PENDING_APPROVAL"}))

    assert (
        await repo.reopen_for_edit("app-1", expected_status="CHECKOUT_PENDING", updated_at=NOW)
        is None
    )
    stored = await repo.get("app-1")
    assert stored is not None
    assert stored.status == "PENDING_APPROVAL"


@pytest.mark.asyncio
async def test_only_one_concurrent_restart_can_restamp_the_application(db, acad) -> None:
    repo = MongoApplicationRepository(db)
    await repo.save(_application(acad))

    first, second = await asyncio.gather(
        repo.restamp_checkout(
            "app-1",
            expected_status="CHECKOUT_PENDING",
            expected_payment_id="pay-first",
            stripe_checkout_session_id="cs_a",
            payment_id="pay-a",
            updated_at=NOW,
        ),
        repo.restamp_checkout(
            "app-1",
            expected_status="CHECKOUT_PENDING",
            expected_payment_id="pay-first",
            stripe_checkout_session_id="cs_b",
            payment_id="pay-b",
            updated_at=NOW,
        ),
    )

    assert sum(result is not None for result in (first, second)) == 1
    stored = await repo.get("app-1")
    assert stored is not None
    # Whichever won, the ids must be a matched PAIR — a half-applied restamp
    # would point the application at one attempt's payment and another's
    # session, and neither webhook would resolve it.
    assert (stored.stripe_checkout_session_id, stored.payment_id) in {
        ("cs_a", "pay-a"),
        ("cs_b", "pay-b"),
    }


@pytest.mark.asyncio
async def test_restamp_misses_when_the_application_left_checkout_pending(db, acad) -> None:
    repo = MongoApplicationRepository(db)
    await repo.save(_application(acad).model_copy(update={"status": "CHECKOUT_EXPIRED"}))

    assert (
        await repo.restamp_checkout(
            "app-1",
            expected_status="CHECKOUT_PENDING",
            expected_payment_id="pay-first",
            stripe_checkout_session_id="cs_a",
            payment_id="pay-a",
            updated_at=NOW,
        )
        is None
    )


@pytest.mark.asyncio
async def test_restamp_accepts_an_application_with_no_payment_stamped_yet(db, acad) -> None:
    """expected_payment_id=None has to match a missing/null field, not nothing."""
    repo = MongoApplicationRepository(db)
    await repo.save(
        _application(acad).model_copy(
            update={"payment_id": None, "stripe_checkout_session_id": None}
        )
    )

    restamped = await repo.restamp_checkout(
        "app-1",
        expected_status="CHECKOUT_PENDING",
        expected_payment_id=None,
        stripe_checkout_session_id="cs_a",
        payment_id="pay-a",
        updated_at=NOW,
    )

    assert restamped is not None
    assert restamped.payment_id == "pay-a"
