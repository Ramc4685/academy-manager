"""Redirect-URL allowlisting for Stripe checkout/return URLs.

Parent-supplied ``success_url``/``cancel_url``/``return_url`` values are passed to Stripe
and become browser redirects, so an unvalidated value is an open-redirect / phishing vector.
This module validates a candidate URL against the server-configured allowlist (the same
origins used for CORS), rejecting anything whose ``scheme://host[:port]`` origin is not
explicitly allowed. Only ``http``/``https`` schemes are permitted; the allowlist itself
decides which exact origins (and therefore which scheme) are acceptable per environment.
"""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlparse

from backend.v2.shared.http.errors import DomainError

_ALLOWED_SCHEMES = frozenset({"http", "https"})


class InvalidRedirectUrl(DomainError):
    """A redirect URL is missing, malformed, or not on the configured allowlist."""

    code = "InvalidRedirectUrl"
    status_code = 400


def _origin(scheme: str, netloc: str) -> str:
    return f"{scheme}://{netloc}"


def _normalize(origin: str) -> str:
    return origin.rstrip("/")


def validate_redirect_url(url: str, *, allowed_origins: Iterable[str]) -> str:
    """Return ``url`` unchanged if its origin is allowlisted, else raise InvalidRedirectUrl.

    ``allowed_origins`` is an iterable of ``scheme://host[:port]`` origins (e.g. the value
    of ``settings.cors_allowed_origins()``). Matching is exact on scheme + host + port.
    """
    if not isinstance(url, str) or not url.strip():
        raise InvalidRedirectUrl("redirect url is required")

    parsed = urlparse(url)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise InvalidRedirectUrl(f"redirect url scheme not allowed: {parsed.scheme!r}")
    if not parsed.netloc:
        # e.g. "//evil.example/x" (scheme-relative) or a relative path — never a valid
        # absolute redirect target.
        raise InvalidRedirectUrl("redirect url must be an absolute http(s) URL")

    candidate = _normalize(_origin(parsed.scheme.lower(), parsed.netloc.lower()))
    allowed = {_normalize(o.lower()) for o in allowed_origins if o and o.strip()}
    if candidate not in allowed:
        raise InvalidRedirectUrl(f"redirect url origin not allowed: {candidate!r}")
    return url
