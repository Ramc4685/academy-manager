"""The placeholder waiver every bootstrapped academy starts with (S09, S47).

Identity writes it at bootstrap; Onboarding treats a live waiver still carrying
exactly this text as "no waiver configured", so families are never asked to
sign setup instructions. Shared because two contexts read it; keep it the
single source.
"""

from __future__ import annotations

DEFAULT_WAIVER_BODY = (
    "Default academy participation waiver. Replace this template before "
    "accepting student registrations."
)


def is_starter_waiver_body(body: object) -> bool:
    """True when ``body`` is still the untouched bootstrap placeholder."""
    return isinstance(body, str) and body.strip() == DEFAULT_WAIVER_BODY
