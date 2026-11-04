"""Recipient ids for prospects (CRM contacts who are not users).

``ResolvedRecipient.user_id`` is required, and the send-time gates, the
unsubscribe token and the delivery log all key on it. A website inquiry has
no user, so it gets a stable synthetic id under this prefix, the same way a
family contact gets ``family_contact:<id>`` (``mongo_audience_resolver.py``).
The prefix is also how ``ProspectOptOutGate`` knows a send is to a prospect
and must consult the email-keyed opt-out list instead of user preferences.
"""

from __future__ import annotations

PROSPECT_RECIPIENT_PREFIX = "crm_contact:"


def prospect_recipient_id(contact_id: str) -> str:
    return f"{PROSPECT_RECIPIENT_PREFIX}{contact_id}"


def prospect_contact_id(user_id: str) -> str | None:
    """The contact id behind a prospect recipient id, else ``None``."""
    if not user_id.startswith(PROSPECT_RECIPIENT_PREFIX):
        return None
    return user_id.removeprefix(PROSPECT_RECIPIENT_PREFIX) or None
