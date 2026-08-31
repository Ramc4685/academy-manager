"""Email categories — the axis every send-time gate reasons over.

Introduced by #555 (recipient unsubscribe) and shared with #556 (bounce
suppression): both gates answer "may this address receive *this kind* of
message", and that question is meaningless without a category. It lives in
``domain/`` because it is a vocabulary, not a policy — the policies (a
preference gate never blocks transactional mail; a hard bounce blocks
everything) live with their gate implementations.
"""

from __future__ import annotations

from enum import StrEnum


class EmailCategory(StrEnum):
    """What kind of message is being sent.

    ``TRANSACTIONAL`` is the default everywhere, so any call site that has not
    been classified is treated as the record of an existing commercial
    relationship and is never dropped by a preference.
    """

    TRANSACTIONAL = "transactional"  # invoice, dunning, login invite, add-card, dues reminder
    DIGEST = "digest"  # parent daily digest, coach daily digest, coach digest test
    CAMPAIGN = "campaign"  # admin bulk campaigns (SendCampaign)


#: Categories a recipient may switch off. ``TRANSACTIONAL`` is deliberately
#: absent: CAN-SPAM's opt-out covers commercial messages, and a family that
#: could suppress its own invoice would be a billing incident, not a
#: preference.
UNSUBSCRIBABLE_CATEGORIES: frozenset[EmailCategory] = frozenset(
    {EmailCategory.DIGEST, EmailCategory.CAMPAIGN}
)
