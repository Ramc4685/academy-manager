"""Key composition for refund idempotency (#930)."""

from __future__ import annotations

from backend.v2.contexts.billing.application.refund_idempotency import refund_keys


def _keys(**overrides: object):
    args: dict[str, object] = {
        "kind": "payment_refund",
        "academy_id": "acad-a",
        "target_id": "pay-1",
        "amount_cents": 3_000,
        "reason": "admin_initiated",
        "idempotency_key": "k-1",
    }
    args.update(overrides)
    return refund_keys(**args)  # type: ignore[arg-type]


def test_same_request_gives_the_same_keys() -> None:
    assert _keys() == _keys()


def test_distinct_client_keys_with_the_same_shape_do_not_collide() -> None:
    a, b = _keys(idempotency_key="k-1"), _keys(idempotency_key="k-2")
    assert a.storage_key != b.storage_key
    assert a.stripe_key != b.stripe_key
    # Same refund shape: the advisory payload key and fingerprint match.
    assert a.payload_key == b.payload_key and a.fingerprint == b.fingerprint


def test_every_key_is_academy_scoped() -> None:
    a, b = _keys(academy_id="acad-a"), _keys(academy_id="acad-b")
    assert a.storage_key != b.storage_key
    assert a.payload_key != b.payload_key
    assert a.stripe_key != b.stripe_key
    assert "acad-a" in a.storage_key and "acad-a" in a.stripe_key


def test_keyless_request_is_keyed_on_its_payload() -> None:
    keys = _keys(idempotency_key=None)
    assert not keys.keyed
    assert keys.storage_key == keys.payload_key


def test_stripe_key_stays_short_whatever_the_client_key() -> None:
    assert len(_keys(idempotency_key="x" * 200).stripe_key) < 255
