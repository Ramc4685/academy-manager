"""Referral programme email copy (L9 C2). COPY AND PREVIEW ONLY.

Nothing here sends. These are the two messages the programme would send once
the owner signs off on the copy: the referring family's reward and the new
family's welcome credit. ``GET /admin/billing/referrals/email-preview``
renders them with sample values so the owner can read them; wiring a send is
a separate change that needs that sign-off, and must stay behind the
programme's switch.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

from backend.v2.composition.trial_nudges import _para


@dataclass(frozen=True)
class ReferralEmail:
    key: str
    subject: str
    inner_html: str


def _dollars(cents: int) -> str:
    return f"${cents / 100:,.2f}".replace(".00", "")


def referrer_reward_email(
    *, academy_name: str, referred_first_name: str, credit_cents: int
) -> ReferralEmail:
    return ReferralEmail(
        key="referral_reward",
        subject=f"Thank you for referring a family to {academy_name}",
        inner_html="".join(
            [
                _para(
                    f"{html.escape(referred_first_name)}'s family has joined "
                    f"{html.escape(academy_name)} with your referral link. Thank you!"
                ),
                _para(
                    f"We have added a <strong>{_dollars(credit_cents)}</strong> credit to "
                    "your account. It comes off your next invoice automatically."
                ),
                _para("You can find your link to share again on your profile page."),
            ]
        ),
    )


def referred_welcome_email(*, academy_name: str, credit_cents: int) -> ReferralEmail:
    return ReferralEmail(
        key="referral_welcome",
        subject=f"A welcome credit from {academy_name}",
        inner_html="".join(
            [
                _para(
                    f"Welcome to {html.escape(academy_name)}! Because a friend referred you, "
                    f"we have added a <strong>{_dollars(credit_cents)}</strong> credit to "
                    "your account."
                ),
                _para("It comes off your next invoice automatically."),
            ]
        ),
    )


def preview(
    *, academy_name: str, referrer_credit_cents: int, referred_credit_cents: int
) -> list[ReferralEmail]:
    """Both messages with sample values, for the owner to read."""
    return [
        referrer_reward_email(
            academy_name=academy_name, referred_first_name="Sam", credit_cents=referrer_credit_cents
        ),
        referred_welcome_email(academy_name=academy_name, credit_cents=referred_credit_cents),
    ]
