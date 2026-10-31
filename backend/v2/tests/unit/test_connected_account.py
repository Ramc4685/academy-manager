from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.v2.contexts.billing.domain.connected_account import ConnectedAccount


def test_requires_academy_id_and_stripe_account_id() -> None:
    with pytest.raises(ValidationError):
        ConnectedAccount()  # type: ignore[call-arg]


def test_new_defaults_to_pending_status_and_empty_capabilities() -> None:
    account = ConnectedAccount.new(
        academy_id="acad-1",
        stripe_account_id="acct_123",
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert account.academy_id == "acad-1"
    assert account.stripe_account_id == "acct_123"
    assert account.status == "pending"
    assert account.capabilities == {}
    assert account.charges_enabled is False
    assert account.payouts_enabled is False
    assert account.created_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert account.updated_at == datetime(2026, 1, 1, tzinfo=UTC)


def test_is_frozen() -> None:
    account = ConnectedAccount.new(academy_id="acad-1", stripe_account_id="acct_123")
    with pytest.raises(ValidationError):
        account.status = "active"  # type: ignore[misc]


def test_is_ready_only_when_charges_enabled() -> None:
    pending = ConnectedAccount.new(academy_id="acad-1", stripe_account_id="acct_123")
    assert pending.is_ready_for_charges() is False

    ready = pending.model_copy(update={"status": "active", "charges_enabled": True})
    assert ready.is_ready_for_charges() is True


def _active(capabilities: dict[str, str]) -> ConnectedAccount:
    return ConnectedAccount.new(academy_id="acad-1", stripe_account_id="acct_123").with_status(
        status="active", charges_enabled=True, capabilities=capabilities
    )


def test_direct_charge_account_is_ready_without_the_transfers_capability() -> None:
    # Direct-charge accounts never request stripe_transfers / v1 transfers.
    account = _active({"card_payments": "active", "us_bank_account_ach_payments": "active"})
    assert account.is_ready_for_charges() is True


def test_destination_era_account_with_transfers_stays_ready() -> None:
    account = _active({"card_payments": "active", "transfers": "active"})
    assert account.is_ready_for_charges() is True


def test_account_without_a_card_payments_snapshot_falls_back_to_charges_enabled() -> None:
    # Rows written before capabilities were tracked, or last touched by a
    # capability.* event for another capability, carry no card_payments key.
    assert _active({}).is_ready_for_charges() is True
    assert _active({"transfers": "active"}).is_ready_for_charges() is True


@pytest.mark.parametrize("state", ["inactive", "pending", "unrequested"])
def test_card_payments_not_active_blocks_charges(state: str) -> None:
    account = _active({"card_payments": state})
    assert account.is_ready_for_charges() is False


def test_charges_disabled_blocks_even_with_card_payments_active() -> None:
    account = _active({"card_payments": "active"}).with_status(
        status="restricted", charges_enabled=False
    )
    assert account.is_ready_for_charges() is False


def test_with_status_updates_status_and_capabilities_and_timestamp() -> None:
    created = datetime(2026, 1, 1, tzinfo=UTC)
    updated_at = datetime(2026, 2, 1, tzinfo=UTC)
    account = ConnectedAccount.new(academy_id="acad-1", stripe_account_id="acct_123", now=created)

    updated = account.with_status(
        status="active",
        capabilities={"card_payments": "active", "us_bank_account_ach_payments": "active"},
        charges_enabled=True,
        payouts_enabled=True,
        now=updated_at,
    )

    assert updated.status == "active"
    assert updated.capabilities == {
        "card_payments": "active",
        "us_bank_account_ach_payments": "active",
    }
    assert updated.charges_enabled is True
    assert updated.payouts_enabled is True
    # Immutable identity preserved; created_at unchanged, updated_at advanced.
    assert updated.academy_id == "acad-1"
    assert updated.stripe_account_id == "acct_123"
    assert updated.created_at == created
    assert updated.updated_at == updated_at


def test_status_must_be_a_known_value() -> None:
    with pytest.raises(ValidationError):
        ConnectedAccount(
            academy_id="acad-1",
            stripe_account_id="acct_123",
            status="banana",  # type: ignore[arg-type]
        )
