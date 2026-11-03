"""Firebase Cloud Messaging sender (mobile M3).

Only built by ``composition.push._build_push_sender`` when
``push_delivery_enabled`` is on. The firebase-admin SDK is synchronous, so the
call runs in a worker thread.

A token is reported dead only on errors that are about the token itself:
unregistered (app uninstalled / token rotated), registered to another sender,
or an INVALID_ARGUMENT whose message names the registration token. A bad
payload is also INVALID_ARGUMENT, and treating that as dead would wipe every
token on the first malformed message.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from firebase_admin import exceptions as firebase_exceptions
from firebase_admin import messaging

from backend.v2.contexts.communications.application.ports import PushSendPort
from backend.v2.contexts.communications.domain.push_device import PushSendResult

#: FCM's per-call multicast limit.
_MAX_TOKENS_PER_CALL = 500


def _is_dead_token_error(exc: BaseException | None) -> bool:
    if isinstance(exc, messaging.UnregisteredError | messaging.SenderIdMismatchError):
        return True
    return isinstance(exc, firebase_exceptions.InvalidArgumentError) and (
        "registration token" in str(exc).lower()
    )


class FcmPushSendPort(PushSendPort):
    def __init__(self, app_provider: Callable[[], Any]) -> None:
        # Lazy so a misconfigured Firebase app fails the send (swallowed by the
        # use case), not app boot.
        self._app_provider = app_provider

    async def send(
        self,
        *,
        tokens: Sequence[str],
        title: str,
        body: str,
        data: Mapping[str, str],
    ) -> PushSendResult:
        sent = 0
        dead: list[str] = []
        for start in range(0, len(tokens), _MAX_TOKENS_PER_CALL):
            chunk = list(tokens[start : start + _MAX_TOKENS_PER_CALL])
            message = messaging.MulticastMessage(
                tokens=chunk,
                notification=messaging.Notification(title=title, body=body),
                data=dict(data),
            )
            response = await asyncio.to_thread(
                messaging.send_each_for_multicast, message, app=self._app_provider()
            )
            for token, outcome in zip(chunk, response.responses, strict=True):
                if outcome.success:
                    sent += 1
                elif _is_dead_token_error(outcome.exception):
                    dead.append(token)
        return PushSendResult(attempted=len(tokens), sent=sent, dead_tokens=tuple(dead))
