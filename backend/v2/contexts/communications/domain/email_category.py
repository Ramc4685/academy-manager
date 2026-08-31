"""Classification of an outbound email, carried through the send seam.

The category is what lets one gate answer different questions for the same
recipient: a spam complaint stops marketing without stopping an invoice, while
a hard bounce stops everything. It is threaded from the send loop into
``EmailSendPort.send`` and consulted by ``RecipientGate`` implementations.
"""

from __future__ import annotations

from enum import StrEnum


class EmailCategory(StrEnum):
    TRANSACTIONAL = "transactional"  # invoice, dunning, login invite, add-card, dues reminder
    DIGEST = "digest"  # parent daily digest, coach daily digest, coach digest test
    CAMPAIGN = "campaign"  # admin bulk campaigns (SendCampaign)


#: Categories a recipient may switch off. TRANSACTIONAL is deliberately absent.
UNSUBSCRIBABLE_CATEGORIES: frozenset[EmailCategory] = frozenset(
    {EmailCategory.DIGEST, EmailCategory.CAMPAIGN}
)
