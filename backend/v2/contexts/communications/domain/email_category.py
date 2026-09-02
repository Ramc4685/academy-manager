"""Email categories — the axis every send-time gate reasons over.

Introduced by #555 (recipient unsubscribe) and shared with #556 (bounce
suppression): both gates answer "may this address receive *this kind* of
message", and that question is meaningless without a category. It lives in
``domain/`` because it is a vocabulary, not a policy — the policies live with
their gate implementations.

The category is what lets the two gates answer *different* questions about the
same recipient: an unsubscribe preference stops digests and campaigns without
stopping an invoice, while a hard bounce stops everything. It is threaded from
the send loops into ``EmailSendPort.send`` and consulted by every
``RecipientGate``.
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
    #: Staff roster alerts (#612): "a student joined / left / moved" pings sent
    #: to the session's coach and to the academy's admins and owners. Operational
    #: rather than commercial, but it is *unsolicited-by-event* mail a coach may
    #: reasonably want to stop, so it is unsubscribable. The family-facing side
    #: of the same events (welcome, waitlist seat opened) stays TRANSACTIONAL:
    #: those are the record of that family's own enrollment.
    NOTIFICATION = "notification"


#: Categories a recipient may switch off. ``TRANSACTIONAL`` is deliberately
#: absent: CAN-SPAM's opt-out covers commercial messages, and a family that
#: could suppress its own invoice would be a billing incident, not a
#: preference. Note this constrains *preferences* only — a hard bounce or a
#: spam complaint suppresses every category, transactional included, because
#: the mailbox itself is gone or hostile.
UNSUBSCRIBABLE_CATEGORIES: frozenset[EmailCategory] = frozenset(
    {EmailCategory.DIGEST, EmailCategory.CAMPAIGN, EmailCategory.NOTIFICATION}
)
