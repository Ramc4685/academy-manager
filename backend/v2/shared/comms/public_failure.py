"""Turn a stored failure string into something safe to show an academy.

Only a bare lower-case code (``email_delivery_failed``) passes. An
``unsubscribed:...`` gate refusal becomes ``recipient_unsubscribed``: email
preferences are tenant-scoped, so that is the academy's own data. Anything else
(provider prose, ``suppressed:complaint``) becomes the fallback: suppressions
come from the list every academy shares, so showing them raw would tell one
academy about another academy's bounce or complaint.
"""

from __future__ import annotations

import re

_PUBLIC_ERROR_CODE = re.compile(r"^[a-z0-9_]{1,64}$")

#: A send refused by the shared suppression list (see ``GatedEmailSendPort``).
#: Also a Mongo ``$regex``, so keep it to syntax both engines share.
SUPPRESSION_REFUSAL = re.compile(r"^suppressed:")
_UNSUBSCRIBE_REFUSAL = "unsubscribed:"


def public_failure(value: str | None, fallback: str) -> str:
    candidate = (value or "").strip().lower()
    if candidate.startswith(_UNSUBSCRIBE_REFUSAL):
        return "recipient_unsubscribed"
    return candidate if _PUBLIC_ERROR_CODE.fullmatch(candidate) else fallback
