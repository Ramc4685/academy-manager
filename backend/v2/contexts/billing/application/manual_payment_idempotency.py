"""Idempotency policy for admin manual-payment recording (issue #511).

``RecordManualPayment`` mints a fresh payment_id per call and is NOT internally
idempotent, so a client retry (e.g. after a post-recording step failed) would
record a SECOND payment and over-credit the invoice. The policy:

- A client-supplied ``Idempotency-Key`` (scoped to the invoice) makes retries of
  the same submission replay, while legitimate repeat payments mint a new key.
  Keyed cache entries carry a payload fingerprint so reusing a key with
  DIFFERENT fields is rejected (mapped to 422) instead of silently replaying the
  first submission's cached result.
- Without a client key, the payload-derived key is a fallback — but a hit there
  is only a *possible* duplicate (two identical cash payments in the 7-day TTL
  are legal), so it surfaces a conflict (mapped to 409) for the caller to
  confirm instead of silently replaying.
- A keyed recording also stamps the payload-derived fallback key so a later
  KEYLESS identical repeat still gets the 409 confirmation.
"""

from __future__ import annotations

import hashlib
from typing import Any, Protocol

from pymongo.errors import DuplicateKeyError


class IdempotencyStore(Protocol):
    async def get(self, key: str) -> dict[str, Any] | None: ...

    async def put(self, key: str, value: dict[str, Any]) -> None: ...


def manual_payment_keys(
    *,
    invoice_id: str,
    amount_cents: int,
    payment_method: str,
    reference_number: str | None,
    notes: str,
    idempotency_key: str | None,
) -> tuple[str, str, str]:
    """Return ``(storage_key, payload_key, payload_fingerprint)``."""
    payload_key = (
        f"manual_payment:{invoice_id}:{amount_cents}:{payment_method}:{reference_number}:{notes}"
    )
    fingerprint = hashlib.sha256(payload_key.encode("utf-8")).hexdigest()
    storage_key = (
        f"manual_payment:{invoice_id}:key:{idempotency_key}" if idempotency_key else payload_key
    )
    return storage_key, payload_key, fingerprint


async def check_manual_payment_idempotency(
    store: IdempotencyStore,
    *,
    storage_key: str,
    payload_fingerprint: str,
    keyed: bool,
) -> dict[str, Any] | None:
    """Return a cached payload to replay, or None to proceed with recording.

    Raises ValueError for the two rejection cases described in the module doc.
    """
    cached = await store.get(storage_key)
    if cached is None:
        return None
    if keyed:
        cached_fingerprint = cached.get("fingerprint")
        if cached_fingerprint is not None and cached_fingerprint != payload_fingerprint:
            raise ValueError(
                "idempotency key reused with a different payload; use a new "
                "Idempotency-Key for a distinct manual payment"
            )
        return dict(cached["payload"])
    raise ValueError(
        "possible duplicate: an identical manual payment was recorded "
        "recently; resend with an Idempotency-Key header to confirm"
    )


async def store_manual_payment_idempotency(
    store: IdempotencyStore,
    *,
    storage_key: str,
    payload_key: str,
    payload_fingerprint: str,
    payload: dict[str, Any],
    keyed: bool,
) -> None:
    """Record the result under the storage key (and, for keyed submissions,
    best-effort under the payload-derived fallback key too)."""
    entry = {"payload": payload, "fingerprint": payload_fingerprint}
    await store.put(storage_key, entry)
    if keyed:
        # Advisory marker only: a concurrent writer or an entry left by an
        # earlier identical payment must not fail a recording that already
        # happened.
        try:
            if await store.get(payload_key) is None:
                await store.put(payload_key, entry)
        except DuplicateKeyError:
            pass
