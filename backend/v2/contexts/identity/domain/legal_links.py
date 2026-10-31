"""Validation for the academy's legal links (Settings overhaul Phase 4 PR 13).

``terms_url`` and ``refund_policy_url`` are rendered as hrefs on the public
page footer, so they are https only (stricter than the privacy link, which
predates this and keeps accepting http). ``javascript:``, ``data:`` and
control characters are refused by ``validate_external_url``; this adds the
https requirement. Blank clears the link.
"""

from __future__ import annotations

from urllib.parse import urlparse

from backend.v2.shared.security.external_url import InvalidExternalUrl, validate_external_url

MAX_LEGAL_URL_LENGTH = 500


def validate_https_url(value: str | None, *, field_label: str) -> str | None:
    """The stripped https URL, ``None`` for blank, else ``ValueError``."""
    try:
        cleaned = validate_external_url(value, field_label=field_label)
    except InvalidExternalUrl as exc:
        raise ValueError(exc.message) from exc
    if cleaned is None:
        return None
    if urlparse(cleaned).scheme.lower() != "https":
        raise ValueError(f"The {field_label} must be a full https:// web address.")
    if len(cleaned) > MAX_LEGAL_URL_LENGTH:
        raise ValueError(f"The {field_label} must be {MAX_LEGAL_URL_LENGTH} characters or fewer.")
    return cleaned


def https_url_or_none(value: object) -> str | None:
    """Read-time guard: a stored value that no longer validates reads as unset."""
    if not isinstance(value, str):
        return None
    try:
        return validate_https_url(value, field_label="link")
    except ValueError:
        return None
