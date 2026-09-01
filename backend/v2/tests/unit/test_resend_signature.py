"""Svix/Resend webhook signature verification (issue #556).

The signature is the *only* authentication on the bounce webhook, so each of
these is a way an attacker (or a mangled proxy) could otherwise write into the
global suppression list.
"""

from __future__ import annotations

import base64
import time

import pytest

from backend.v2.contexts.communications.domain.errors import InvalidProviderSignature
from backend.v2.contexts.communications.infrastructure.resend_signature import (
    sign_resend_payload,
    verify_resend_signature,
)

SECRET = "whsec_" + base64.b64encode(b"super-secret-key-material").decode()
BODY = b'{"type":"email.bounced","data":{"to":["dead@example.com"]}}'


def _headers(
    *, secret: str = SECRET, payload: bytes = BODY, ts: str | None = None
) -> dict[str, str]:
    timestamp = ts or str(int(time.time()))
    return {
        "svix-id": "msg_2abc",
        "svix-timestamp": timestamp,
        "svix-signature": sign_resend_payload(
            svix_id="msg_2abc", timestamp=timestamp, payload=payload, secret=secret
        ),
    }


def test_valid_signature_is_accepted() -> None:
    verify_resend_signature(payload=BODY, headers=_headers(), secret=SECRET)


def test_signature_from_a_different_secret_is_rejected() -> None:
    forged = _headers(secret="whsec_" + base64.b64encode(b"attacker-key").decode())
    with pytest.raises(InvalidProviderSignature):
        verify_resend_signature(payload=BODY, headers=forged, secret=SECRET)


def test_body_mutated_by_one_byte_is_rejected() -> None:
    headers = _headers()
    tampered = BODY.replace(b"dead@example.com", b"dead@example.corn")
    with pytest.raises(InvalidProviderSignature):
        verify_resend_signature(payload=tampered, headers=headers, secret=SECRET)


def test_replayed_old_timestamp_is_rejected() -> None:
    stale = str(int(time.time()) - 600)
    with pytest.raises(InvalidProviderSignature):
        verify_resend_signature(payload=BODY, headers=_headers(ts=stale), secret=SECRET)


def test_multi_signature_header_accepts_when_one_entry_matches() -> None:
    headers = _headers()
    headers["svix-signature"] = (
        "v1,AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA= " + headers["svix-signature"]
    )
    verify_resend_signature(payload=BODY, headers=headers, secret=SECRET)


def test_missing_headers_are_rejected() -> None:
    with pytest.raises(InvalidProviderSignature):
        verify_resend_signature(payload=BODY, headers={}, secret=SECRET)


def test_blank_secret_never_verifies() -> None:
    """Fail-closed: an unconfigured secret must not authenticate anything.

    The Stripe Connect state secret falls back to ``""`` (issue #547); that
    pattern would make every forged bounce report valid here.
    """
    with pytest.raises(InvalidProviderSignature):
        verify_resend_signature(payload=BODY, headers=_headers(), secret="")
