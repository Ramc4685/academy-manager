"""Turn a stored failure string into something safe to show an academy.

Only a bare lower-case code (``email_delivery_failed``) passes; anything else
(provider prose, ``suppressed:complaint``, ``unsubscribed:...``) becomes the
fallback. Gate reasons come from the shared suppression list, so showing them
raw would tell one academy about another academy's bounce or complaint.
"""

from __future__ import annotations

import re

_PUBLIC_ERROR_CODE = re.compile(r"^[a-z0-9_]{1,64}$")

#: Send-time gate refusals (see ``GatedEmailSendPort``).
GATE_REFUSAL = re.compile(r"^(suppressed|unsubscribed):")


def public_failure(value: str | None, fallback: str) -> str:
    candidate = (value or "").strip().lower()
    return candidate if _PUBLIC_ERROR_CODE.fullmatch(candidate) else fallback
