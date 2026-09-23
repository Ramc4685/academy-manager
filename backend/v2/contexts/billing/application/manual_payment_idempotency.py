"""Idempotency policy for admin manual-payment recording (issue #511).

``RecordManualPayment`` records whatever it is asked to, so a client retry (e.g.
after a post-recording step failed) or a double-click would record a SECOND
payment and over-credit the invoice. The policy:

- A client-supplied ``Idempotency-Key`` (scoped to the academy and the invoice)
  makes retries of the same submission replay, while legitimate repeat
  payments mint a new key. Keyed cache entries carry a payload fingerprint so
  reusing a key with DIFFERENT fields is rejected (mapped to 422) instead of
  silently replaying the first submission's cached result.
- Without a client key, the payload-derived key is a fallback — but a hit there
  is only a *possible* duplicate (two identical cash payments in the 7-day TTL
  are legal), so it surfaces a conflict (mapped to 409) for the caller to
  confirm instead of silently replaying.
- A keyed recording also stamps the payload-derived fallback key so a later
  KEYLESS identical repeat still gets the 409 confirmation.

Concurrency (A5): the cache check alone is check-then-act, so two submits that
both miss the cache both recorded (a double-click recorded one payment per
click). Each recording therefore CLAIMS its key first, an insert the unique
``idempotency_keys.key`` index lets exactly one caller win. The loser replays
the winner's result when it is there, and otherwise gets a 409: "in progress"
for a keyed submit, "possible duplicate" for a keyless one. A keyed claim whose
owner died is taken over after :data:`IN_FLIGHT_WINDOW`; that is safe because a
keyed recording uses a payment id derived from the key, so the ledger's own
idempotency keys dedupe whatever the dead attempt already wrote.

Tenancy (#544): the store is global, so every key embeds the request academy.
Without it, academy B sending academy A's invoice id got A's cached payment
(keyed) or a 409 that confirmed the invoice exists (keyless), not a 404.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from pymongo.errors import DuplicateKeyError

from backend.v2.contexts.billing.application.ports import LedgerRepository
from backend.v2.contexts.billing.application.use_cases.record_manual_payment import (
    RecordManualPayment,
    RecordManualPaymentCommand,
)
from backend.v2.contexts.billing.domain.billing_audit import BillingAuditEntry
from backend.v2.shared.ids import new_ulid

#: A keyed claim younger than this is a submission still in flight; an older
#: one is assumed abandoned (its process died) and may be taken over.
IN_FLIGHT_WINDOW = timedelta(seconds=60)


class IdempotencyStore(Protocol):
    async def get(self, key: str) -> dict[str, Any] | None: ...

    async def put(self, key: str, value: dict[str, Any]) -> None: ...


class AuditLog(Protocol):
    async def append(self, entry: BillingAuditEntry) -> None: ...


def manual_payment_keys(
    *,
    academy_id: str,
    invoice_id: str,
    amount_cents: int,
    payment_method: str,
    reference_number: str | None,
    notes: str,
    idempotency_key: str | None,
) -> tuple[str, str, str]:
    """Return ``(storage_key, payload_key, payload_fingerprint)``."""
    payload_key = (
        f"manual_payment:{academy_id}:{invoice_id}:{amount_cents}:{payment_method}:"
        f"{reference_number}:{notes}"
    )
    fingerprint = hashlib.sha256(payload_key.encode("utf-8")).hexdigest()
    storage_key = (
        f"manual_payment:{academy_id}:{invoice_id}:key:{idempotency_key}"
        if idempotency_key
        else payload_key
    )
    return storage_key, payload_key, fingerprint


def manual_payment_id(storage_key: str) -> str:
    """The payment id a keyed submission records under, the same on every retry."""
    return "manual-k" + hashlib.sha256(storage_key.encode("utf-8")).hexdigest()[:32]


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
        _reject_other_payload(cached, payload_fingerprint)
        return dict(cached["payload"])
    raise ValueError(_POSSIBLE_DUPLICATE)


async def claim_manual_payment(
    store: IdempotencyStore,
    *,
    storage_key: str,
    payload_fingerprint: str,
    keyed: bool,
    now: datetime,
) -> dict[str, Any] | None:
    """Claim the right to record, or return the payload a concurrent winner cached.

    Returns None when this caller must record. Raises ValueError (409/422) when
    another submission holds the claim.
    """
    claim_key = f"{storage_key}:claim"
    claim = {"started_at": now.isoformat(), "fingerprint": payload_fingerprint}
    try:
        await store.put(claim_key, claim)
        return None
    except DuplicateKeyError:
        pass
    cached = await check_manual_payment_idempotency(
        store, storage_key=storage_key, payload_fingerprint=payload_fingerprint, keyed=keyed
    )
    if cached is not None:
        return cached
    if not keyed:
        raise ValueError(_POSSIBLE_DUPLICATE)
    held = await store.get(claim_key) or {}
    _reject_other_payload(held, payload_fingerprint)
    started_at = held.get("started_at")
    if started_at and datetime.fromisoformat(str(started_at)) > now - IN_FLIGHT_WINDOW:
        raise ValueError(
            "manual payment already in progress for this Idempotency-Key; "
            "wait a moment and retry with the same key"
        )
    return None  # abandoned claim: the key-derived payment id makes the takeover safe


async def store_manual_payment_idempotency(
    store: IdempotencyStore,
    *,
    storage_key: str,
    payload_key: str,
    payload_fingerprint: str,
    payload: dict[str, Any],
    keyed: bool,
) -> dict[str, Any]:
    """Record the result under the storage key (and, for keyed submissions,
    best-effort under the payload-derived fallback key too).

    Returns the payload the caller should answer with: its own, or the one a
    concurrent taker-over of an abandoned claim stored first.
    """
    entry = {"payload": payload, "fingerprint": payload_fingerprint}
    try:
        await store.put(storage_key, entry)
    except DuplicateKeyError:
        stored = await store.get(storage_key)
        if stored is None:
            raise
        payload = dict(stored["payload"])
    if keyed:
        # Advisory marker only: a concurrent writer or an entry left by an
        # earlier identical payment must not fail a recording that already
        # happened.
        try:
            if await store.get(payload_key) is None:
                await store.put(payload_key, entry)
        except DuplicateKeyError:
            pass
    return payload


async def record_manual_payment_once(
    *,
    store: IdempotencyStore,
    ledger: LedgerRepository,
    audit: AuditLog,
    academy_id: str,
    invoice_id: str,
    amount_cents: int,
    payment_method: str,
    reference_number: str | None,
    notes: str,
    actor_id: str | None,
    idempotency_key: str | None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    """Record one manual payment under the policy above and audit who did it.

    ``academy_id`` is the REQUEST tenant; it scopes the idempotency keys and
    stamps the audit entry the family timeline renders.
    """
    keyed = bool(idempotency_key)
    storage_key, payload_key, fingerprint = manual_payment_keys(
        academy_id=academy_id,
        invoice_id=invoice_id,
        amount_cents=amount_cents,
        payment_method=payment_method,
        reference_number=reference_number,
        notes=notes,
        idempotency_key=idempotency_key,
    )
    cached = await check_manual_payment_idempotency(
        store, storage_key=storage_key, payload_fingerprint=fingerprint, keyed=keyed
    )
    if cached is not None:
        return cached
    # The invoice is looked up (tenant-scoped) BEFORE any claim is written, so
    # an id from another academy is a plain "not found" that leaves no trace.
    if await ledger.get_invoice(invoice_id) is None:
        raise ValueError(f"invoice {invoice_id!r} not found")
    cached = await claim_manual_payment(
        store, storage_key=storage_key, payload_fingerprint=fingerprint, keyed=keyed, now=clock()
    )
    if cached is not None:
        return cached
    result = await RecordManualPayment(ledger=ledger, clock=clock).execute(
        RecordManualPaymentCommand(
            invoice_id=invoice_id,
            amount_cents=amount_cents,
            payment_method=payment_method,  # type: ignore[arg-type]
            reference_number=reference_number,
            notes=notes,
            payment_id=manual_payment_id(storage_key) if keyed else None,
        )
    )
    # Record the idempotency result right after the durable money movement and
    # BEFORE the audit append, so an audit failure cannot drive a retry into a
    # second payment.
    payload = await store_manual_payment_idempotency(
        store,
        storage_key=storage_key,
        payload_key=payload_key,
        payload_fingerprint=fingerprint,
        payload=result.model_dump(mode="python"),
        keyed=keyed,
    )
    # P0-4: append-only audit of who recorded the manual payment (money
    # movement), mirroring the refund audit. Overpayment that became an account
    # credit is captured in `after` so the trail explains where the excess went.
    await audit.append(
        BillingAuditEntry(
            audit_id=f"baud-{new_ulid()}",
            academy_id=academy_id,
            action="manual_payment_recorded",
            actor_id=actor_id or "system",
            at=clock(),
            invoice_id=invoice_id,
            payment_id=result.payment_id,
            reason=payment_method,
            after={
                "amount_cents": amount_cents,
                "invoice_status": result.invoice_status,
                "balance_due_cents": result.balance_due_cents,
                "overpayment_credit_cents": result.overpayment_credit_cents,
            },
        )
    )
    return payload


_POSSIBLE_DUPLICATE = (
    "possible duplicate: an identical manual payment was recorded "
    "recently; resend with an Idempotency-Key header to confirm"
)


def _reject_other_payload(entry: dict[str, Any], payload_fingerprint: str) -> None:
    fingerprint = entry.get("fingerprint")
    if fingerprint is not None and fingerprint != payload_fingerprint:
        raise ValueError(
            "idempotency key reused with a different payload; use a new "
            "Idempotency-Key for a distinct manual payment"
        )
