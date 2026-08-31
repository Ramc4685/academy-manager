"""ResolveUnsubscribeToken — turn an emailed token into a recipient.

The single choke point where a token becomes authority to change someone's
preferences. Two rules live here, and nowhere else:

* the token's ``academy_id`` must equal the tenant the request resolved to, so
  a token minted under one academy cannot act under another;
* every failure — bad signature, wrong version, unknown tenant, garbage — is
  the same ``UnsubscribeTokenInvalid``, so the endpoint reveals nothing about
  which ids exist.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.v2.contexts.communications.application.unsubscribe_token import (
    verify_unsubscribe_token,
)


class UnsubscribeTokenInvalid(Exception):
    """The token is not one of ours, or not valid for this tenant."""


@dataclass(frozen=True, slots=True)
class ResolvedUnsubscribeTarget:
    academy_id: str
    user_id: str


@dataclass
class ResolveUnsubscribeToken:
    secret: str | None

    def execute(
        self, token: str, *, expected_academy_id: str | None = None
    ) -> ResolvedUnsubscribeTarget:
        resolved = verify_unsubscribe_token(token, secret=self.secret)
        if resolved is None:
            raise UnsubscribeTokenInvalid("unsubscribe token could not be verified")
        academy_id, user_id = resolved
        if expected_academy_id and academy_id != expected_academy_id:
            raise UnsubscribeTokenInvalid("unsubscribe token belongs to another tenant")
        return ResolvedUnsubscribeTarget(academy_id=academy_id, user_id=user_id)
