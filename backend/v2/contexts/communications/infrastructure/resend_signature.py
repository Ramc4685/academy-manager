"""Svix (Resend) webhook signature verification.

Resend signs webhooks with Svix. The ``svix`` package is deliberately NOT a
dependency: the scheme is a five-line HMAC and this repo already verifies
HMACs by hand (``identity.application.use_cases.stripe_connect._verify_state``),
so we copy that idiom rather than adding a package for it.

The scheme:

* headers ``svix-id``, ``svix-timestamp``, ``svix-signature``;
* the secret is ``whsec_<base64>`` — the *key material* is the base64-decoded
  tail, not the printable string;
* the signed content is exactly ``f"{svix_id}.{svix_timestamp}.{raw_body}"``
  over the RAW request bytes. Re-serializing a parsed dict changes key order
  and whitespace and will never verify;
* ``svix-signature`` holds space-separated ``v1,<base64 sig>`` entries — more
  than one during key rotation — and any matching entry accepts;
* a timestamp further than ``TIMESTAMP_TOLERANCE_SECONDS`` from now is
  rejected, so a captured request cannot be replayed indefinitely.

Fail-closed: there is no empty-secret fallback here. A blank secret raises,
and composition refuses to mount the route at all rather than verifying with a
key an attacker could guess. (The Stripe Connect state secret at
``composition/admin.py`` does fall back to ``""`` — see issue #547; that
pattern is deliberately not reproduced.)
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import time
from collections.abc import Mapping
from dataclasses import dataclass

from backend.v2.contexts.communications.domain.errors import InvalidProviderSignature

#: How far an inbound ``svix-timestamp`` may be from our clock. Svix's own
#: recommended tolerance; wide enough for clock skew, narrow enough that a
#: captured request stops being replayable within minutes.
TIMESTAMP_TOLERANCE_SECONDS = 300

_SECRET_PREFIX = "whsec_"


def _key_material(secret: str) -> bytes:
    raw = secret.strip()
    if not raw:
        raise InvalidProviderSignature("webhook signing secret is not configured")
    if raw.startswith(_SECRET_PREFIX):
        raw = raw[len(_SECRET_PREFIX) :]
    try:
        return base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        # A secret that is not base64 is still a secret; use its bytes rather
        # than silently verifying nothing.
        return raw.encode("utf-8")


def sign_resend_payload(*, svix_id: str, timestamp: str, payload: bytes, secret: str) -> str:
    """Produce the ``v1,<b64>`` signature entry for a payload.

    Exported so tests (and any future replay tool) can build a genuine
    signature instead of hand-rolling a second, possibly divergent, copy of
    the scheme.
    """
    signed = b".".join([svix_id.encode("utf-8"), timestamp.encode("utf-8"), payload])
    mac = hmac.new(_key_material(secret), signed, hashlib.sha256).digest()
    return "v1," + base64.b64encode(mac).decode("ascii")


def verify_resend_signature(
    *,
    payload: bytes,
    headers: Mapping[str, str],
    secret: str,
    now: float | None = None,
) -> None:
    """Raise ``InvalidProviderSignature`` unless the request is authentic."""
    lookup = {str(k).lower(): v for k, v in headers.items()}
    svix_id = (lookup.get("svix-id") or "").strip()
    timestamp = (lookup.get("svix-timestamp") or "").strip()
    signature_header = (lookup.get("svix-signature") or "").strip()
    if not (svix_id and timestamp and signature_header):
        raise InvalidProviderSignature("missing svix signature headers")

    try:
        sent_at = int(timestamp)
    except ValueError as exc:
        raise InvalidProviderSignature("svix-timestamp is not an integer") from exc
    current = time.time() if now is None else now
    if abs(current - sent_at) > TIMESTAMP_TOLERANCE_SECONDS:
        raise InvalidProviderSignature("svix-timestamp outside replay tolerance")

    expected = sign_resend_payload(
        svix_id=svix_id, timestamp=timestamp, payload=payload, secret=secret
    )
    _, _, expected_b64 = expected.partition(",")
    for entry in signature_header.split(" "):
        version, _, candidate = entry.strip().partition(",")
        if version != "v1" or not candidate:
            continue
        if hmac.compare_digest(expected_b64, candidate):
            return
    raise InvalidProviderSignature("no signature entry matched")


@dataclass(frozen=True, slots=True)
class ResendSignatureVerifier:
    """``ProviderSignatureVerifier`` bound to one configured secret."""

    secret: str

    def verify(self, *, payload: bytes, headers: Mapping[str, str]) -> None:
        verify_resend_signature(payload=payload, headers=headers, secret=self.secret)
