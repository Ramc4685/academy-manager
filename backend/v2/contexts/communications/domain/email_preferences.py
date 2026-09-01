"""Recipient email preferences (#555).

One row per recipient who has actually expressed a choice. The absence of a
row means "opted in to everything" — we never pre-create rows, so this
collection is a record of decisions, not a shadow copy of the user directory.

Only the categories in ``UNSUBSCRIBABLE_CATEGORIES`` are representable here.
There is deliberately no ``transactional_opted_out`` flag: it would be a field
that must never be honoured, and a field that must never be honoured is a bug
waiting to be "fixed".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.v2.contexts.communications.domain.email_category import EmailCategory


def normalize_email(email: str | None) -> str | None:
    """Lower/strip an address for audit lookups. ``None`` stays ``None``."""
    if not email:
        return None
    cleaned = email.strip().lower()
    return cleaned or None


@dataclass(frozen=True, slots=True)
class EmailPreferences:
    """What one recipient has switched off."""

    preference_id: str
    user_id: str
    email: str | None
    campaigns_opted_out: bool = False
    digests_opted_out: bool = False
    opted_out_at: datetime | None = None
    source: str | None = None  # "link" | "portal" | "admin"
    updated_at: datetime | None = None

    def blocks(self, category: EmailCategory) -> bool:
        """True when this recipient has switched ``category`` off.

        ``TRANSACTIONAL`` can never be blocked — see the module docstring.
        """
        if category is EmailCategory.CAMPAIGN:
            return self.campaigns_opted_out
        if category is EmailCategory.DIGEST:
            return self.digests_opted_out
        return False

    @property
    def opted_out_of_everything(self) -> bool:
        return self.campaigns_opted_out and self.digests_opted_out
