"""Cloudflare Turnstile server-side check for the public trial booking (L9).

``verify`` posts the widget's token to Cloudflare's ``siteverify`` endpoint
with the academy platform's secret. It FAILS CLOSED: a missing or oversized
token, a network error, a timeout or anything but ``success: true`` is a
refusal, and so is a token solved on another host than the one the booking
was posted to (one tenant's widget cannot vouch for another's page). With no
secret configured the check is skipped in dev and CI (no widget), but a
``required`` verifier (production) refuses every booking until
``V2_TURNSTILE_SECRET_KEY`` is set. Only the booking branch calls it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import httpx

logger = logging.getLogger(__name__)

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
#: Cloudflare documents tokens of up to 2048 characters.
MAX_TOKEN_LEN = 2048
_TIMEOUT_SECONDS = 5.0


class TurnstileVerifier:
    def __init__(
        self,
        secret: str | None,
        *,
        required: bool = False,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._secret = (secret or "").strip() or None
        self._required = required
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(timeout=_TIMEOUT_SECONDS)
        )

    async def verify(
        self, token: str | None, *, remote_ip: str | None, hostname: str | None = None
    ) -> bool:
        if self._secret is None:
            if self._required:
                logger.error("public.turnstile_secret_missing")
            return not self._required
        if not token or len(token) > MAX_TOKEN_LEN:
            return False
        data = {"secret": self._secret, "response": token}
        if remote_ip:
            data["remoteip"] = remote_ip
        try:
            async with self._client_factory() as client:
                response = await client.post(SITEVERIFY_URL, data=data)
            if response.status_code != 200:
                return False
            body = response.json()
            if body.get("success") is not True:
                return False
            return hostname is None or str(body.get("hostname", "")).lower() == hostname.lower()
        except Exception:
            logger.warning("public.turnstile_verify_failed", exc_info=True)
            return False
