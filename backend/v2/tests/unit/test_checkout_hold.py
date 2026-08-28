"""Checkout-hold domain rules + the autopay guard that consumes them (issue #434).

Bug reproduced here: a parent opens a Checkout Session and pays manually. The success
webhook has not drained yet, so the invoice still reads ``open``. The hourly dunning tick
reads it, charges off-session under a fresh ``retry_scope`` key, and the parent pays
twice. Without the hold, ``test_charge_is_refused_while_a_checkout_session_is_open``
fails: the gateway records a second charge.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from backend.v2.contexts.billing.application.use_cases.charge_invoice_via_autopay import (
    ChargeInvoiceViaAutopay,
)
from backend.v2.contexts.billing.domain.checkout_hold import (
    CHECKOUT_HOLD_DECLINE_CODE,
    CHECKOUT_HOLD_WINDOW,
    active_checkout_hold,
    place_checkout_hold,
    release_checkout_hold,
)
from backend.v2.contexts.billing.domain.ledger import LedgerInvoice
from backend.v2.tests.unit.test_charge_autopay_use_case import (
    FakeLedgerRepo,
    FakeStripeSucceeds,
)

NOW = datetime(2026, 6, 14, 12, 0, 0, tzinfo=UTC)


def _invoice(**overrides) -> LedgerInvoice:
    base = {
        "invoice_id": "inv-1",
        "academy_id": "acad-1",
        "parent_id": "parent-1",
        "student_id": "s-1",
        "enrollment_id": "enr-1",
        "period": "2026-06",
        "status": "open",
        "subtotal_cents": 10_000,
        "discount_cents": 0,
        "total_cents": 10_000,
        "balance_due_cents": 10_000,
        "currency": "usd",
        "due_date": date(2026, 6, 30),
        "created_at": NOW,
        "updated_at": NOW,
    }
    base.update(overrides)
    return LedgerInvoice(**base)  # type: ignore[arg-type]


class _ActiveEnrollmentAutopay:
    def __init__(self) -> None:
        self.outcomes: list[tuple[str, str, str | None]] = []

    async def get_autopay_enrollment_status(self, *, enrollment_id: str) -> str | None:
        return "active"

    async def record_attempt_outcome(
        self, *, enrollment_id: str, outcome: str, occurred_at, failure_code
    ) -> None:
        self.outcomes.append((enrollment_id, outcome, failure_code))


# ---------------------------------------------------------------------------
# Domain
# ---------------------------------------------------------------------------


def test_place_then_read_hold_returns_the_session_id() -> None:
    held = place_checkout_hold(_invoice(), checkout_session_id="cs_test_open", now=NOW)

    assert held.checkout_hold_session_id == "cs_test_open"
    assert held.checkout_hold_started_at == NOW
    assert active_checkout_hold(held, now=NOW) == "cs_test_open"


def test_hold_expires_at_the_window_edge_so_collection_always_resumes() -> None:
    held = place_checkout_hold(_invoice(), checkout_session_id="cs_test_open", now=NOW)

    just_inside = NOW + CHECKOUT_HOLD_WINDOW - timedelta(seconds=1)
    assert active_checkout_hold(held, now=just_inside) == "cs_test_open"
    assert active_checkout_hold(held, now=NOW + CHECKOUT_HOLD_WINDOW) is None


def test_unheld_invoice_has_no_active_hold() -> None:
    assert active_checkout_hold(_invoice(), now=NOW) is None


def test_release_clears_both_fields() -> None:
    held = place_checkout_hold(_invoice(), checkout_session_id="cs_test_open", now=NOW)

    released = release_checkout_hold(held, now=NOW, checkout_session_id="cs_test_open")

    assert released is not None
    assert released.checkout_hold_session_id is None
    assert released.checkout_hold_started_at is None
    assert active_checkout_hold(released, now=NOW) is None


def test_release_is_a_no_op_when_nothing_is_held() -> None:
    assert release_checkout_hold(_invoice(), now=NOW) is None


def test_late_webhook_for_a_superseded_session_does_not_unlock_the_newer_one() -> None:
    # Parent abandoned cs_old and re-opened the pay link, minting cs_new. The
    # expired-webhook for cs_old must not release the hold cs_new is holding, or
    # the double-charge race is back for the session still in flight.
    held = place_checkout_hold(_invoice(), checkout_session_id="cs_new", now=NOW)

    assert release_checkout_hold(held, now=NOW, checkout_session_id="cs_old") is None


def test_newer_session_replaces_the_older_hold() -> None:
    first = place_checkout_hold(_invoice(), checkout_session_id="cs_old", now=NOW)
    later = NOW + timedelta(minutes=5)

    second = place_checkout_hold(first, checkout_session_id="cs_new", now=later)

    assert second.checkout_hold_session_id == "cs_new"
    assert second.checkout_hold_started_at == later


def test_hold_without_a_timestamp_fails_open_rather_than_locking_forever() -> None:
    malformed = _invoice(checkout_hold_session_id="cs_orphan")

    assert active_checkout_hold(malformed, now=NOW) is None


# ---------------------------------------------------------------------------
# ChargeInvoiceViaAutopay guard — the actual double charge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_charge_is_refused_while_a_checkout_session_is_open() -> None:
    """The bug: dunning fires mid-checkout and collects the same balance twice."""
    invoice = place_checkout_hold(_invoice(), checkout_session_id="cs_test_open", now=NOW)
    ledger = FakeLedgerRepo([invoice])
    stripe = FakeStripeSucceeds()
    enrollment = _ActiveEnrollmentAutopay()

    result = await ChargeInvoiceViaAutopay(
        ledger=ledger,
        stripe=stripe,
        enrollment_autopay=enrollment,
        clock=lambda: NOW,
    ).execute("inv-1", retry_scope="dunning-attempt:1")

    assert result.success is False
    assert result.decline_code == CHECKOUT_HOLD_DECLINE_CODE
    # No second charge, and no attempt row: this is not a decline the parent caused.
    assert stripe.create_calls == []
    assert ledger.payment_attempts == []
    assert ledger.recorded_payments == []
    assert enrollment.outcomes == []


@pytest.mark.asyncio
async def test_charge_proceeds_once_the_hold_is_released() -> None:
    """A genuinely unpaid invoice still gets collected after the session ends."""
    held = place_checkout_hold(_invoice(), checkout_session_id="cs_test_open", now=NOW)
    released = release_checkout_hold(held, now=NOW, checkout_session_id="cs_test_open")
    assert released is not None
    ledger = FakeLedgerRepo([released])
    stripe = FakeStripeSucceeds()

    result = await ChargeInvoiceViaAutopay(
        ledger=ledger,
        stripe=stripe,
        enrollment_autopay=_ActiveEnrollmentAutopay(),
        clock=lambda: NOW,
    ).execute("inv-1", retry_scope="dunning-attempt:1")

    assert result.success is True
    assert len(stripe.create_calls) == 1


@pytest.mark.asyncio
async def test_charge_proceeds_once_the_hold_window_lapses() -> None:
    """Backstop: a lost terminal webhook must not stall collection forever."""
    invoice = place_checkout_hold(_invoice(), checkout_session_id="cs_test_open", now=NOW)
    ledger = FakeLedgerRepo([invoice])
    stripe = FakeStripeSucceeds()
    later = NOW + CHECKOUT_HOLD_WINDOW + timedelta(minutes=1)

    result = await ChargeInvoiceViaAutopay(
        ledger=ledger,
        stripe=stripe,
        enrollment_autopay=_ActiveEnrollmentAutopay(),
        clock=lambda: later,
    ).execute("inv-1", retry_scope="dunning-attempt:1")

    assert result.success is True
    assert len(stripe.create_calls) == 1
