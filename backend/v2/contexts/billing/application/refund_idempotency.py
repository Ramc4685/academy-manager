"""Idempotency policy for refunds (#930).

A refund's SHAPE (payment or invoice + amount + reason) does not identify it:
an owner can legitimately refund $30 "class cancelled" twice. Before #930 both
refund paths keyed their dedupe on that shape, so the second real refund inside
the 7-day TTL silently replayed the first result and no money moved. The
policy, mirroring manual payments (#511):

- A client-supplied ``Idempotency-Key`` identifies ONE refund attempt: a retry
  with the same key replays the first result; a new key is a new refund that
  either executes or fails loudly (``RefundExceedsAmount``, "no refundable
  allocated payment"). Keyed entries carry a payload fingerprint, so a key
  reused for a DIFFERENT refund is rejected (422) instead of replaying.
- Without a key, the payload-derived key is only a *possible* duplicate: the
  repeat is rejected with a 409 the owner confirms by resending with a key.
  Nothing is ever replayed or dropped silently on a keyless request.
- A keyed refund also stamps the payload-derived key (advisory), so a later
  keyless identical repeat still gets the 409.

Tenancy (#544, #849): the store is global and payment/invoice ids are not
guaranteed globally unique, so every key embeds the academy that owns the
refunded record.

The Stripe idempotency key is derived from the same storage key, so it is
deterministic per request: a retry whose cached result was lost reaches Stripe
with the same key and Stripe returns the original refund instead of a second.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.billing.domain.errors import (
    RefundIdempotencyKeyReused,
    RefundPossibleDuplicate,
)

RefundKind = Literal["payment_refund", "invoice_refund"]


class IdempotencyStore(Protocol):
    async def get(self, key: str) -> dict[str, Any] | None: ...

    async def put(self, key: str, value: dict[str, Any]) -> None: ...


@dataclass(frozen=True)
class RefundKeys:
    """The keys one refund request is deduped and sent to Stripe under."""

    storage_key: str
    payload_key: str
    fingerprint: str
    keyed: bool
    #: Deterministic per request; stable across retries of the same request.
    request_digest: str
    #: Sent to Stripe as the ``Idempotency-Key`` of the refund create call.
    stripe_key: str


def refund_keys(
    *,
    kind: RefundKind,
    academy_id: str,
    target_id: str,
    amount_cents: int | None,
    reason: str,
    idempotency_key: str | None,
) -> RefundKeys:
    payload_key = f"{kind}:{academy_id}:{target_id}:{amount_cents}:{reason}"
    fingerprint = _sha256(payload_key)
    storage_key = (
        f"{kind}:{academy_id}:{target_id}:key:{idempotency_key}" if idempotency_key else payload_key
    )
    digest = _sha256(storage_key)[:32]
    return RefundKeys(
        storage_key=storage_key,
        payload_key=payload_key,
        fingerprint=fingerprint,
        keyed=bool(idempotency_key),
        request_digest=digest,
        stripe_key=f"{kind}:{academy_id}:{target_id}:{digest}",
    )


async def replay_or_reject(store: IdempotencyStore, keys: RefundKeys) -> dict[str, Any] | None:
    """Return the cached payload of THIS request, or None to execute.

    Raises ``RefundPossibleDuplicate`` for a keyless repeat and
    ``RefundIdempotencyKeyReused`` for a key reused with another payload.
    """
    cached = await store.get(keys.storage_key)
    if cached is None:
        return None
    if not keys.keyed:
        raise RefundPossibleDuplicate(
            "possible duplicate: an identical refund was issued recently; "
            "resend with an Idempotency-Key to confirm a second refund"
        )
    fingerprint = cached.get("fingerprint")
    if fingerprint is not None and fingerprint != keys.fingerprint:
        raise RefundIdempotencyKeyReused(
            "idempotency key reused with a different refund; use a new "
            "Idempotency-Key for a distinct refund"
        )
    return dict(cached["payload"])


async def remember(
    store: IdempotencyStore, keys: RefundKeys, payload: dict[str, Any]
) -> dict[str, Any]:
    """Cache the result of a refund that already moved money.

    Returns the payload the caller answers with: its own, or, for a keyed
    request that raced a concurrent retry of itself, the one stored first
    (Stripe's idempotency key made both the same refund).
    """
    entry = {"payload": payload, "fingerprint": keys.fingerprint}
    try:
        await store.put(keys.storage_key, entry)
    except DuplicateKeyError:
        if keys.keyed:
            stored = await store.get(keys.storage_key)
            if stored is not None:
                payload = dict(stored["payload"])
        # A keyless race means two refunds really happened: answer with ours.
    if keys.keyed:
        # Advisory marker only; it must never fail a refund that happened.
        try:
            if await store.get(keys.payload_key) is None:
                await store.put(keys.payload_key, entry)
        except DuplicateKeyError:
            pass
    return payload


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
