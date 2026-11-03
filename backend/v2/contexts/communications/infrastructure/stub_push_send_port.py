"""In-memory push sender for tests and local dev (mirrors ``StubEmailSendPort``)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from backend.v2.contexts.communications.application.ports import PushSendPort
from backend.v2.contexts.communications.domain.push_device import PushSendResult


@dataclass
class StubPushSendPort(PushSendPort):
    sent: list[dict[str, Any]] = field(default_factory=list)
    #: Tokens to report as dead, so tests can drive the pruning path.
    dead: set[str] = field(default_factory=set)

    async def send(
        self,
        *,
        tokens: Sequence[str],
        title: str,
        body: str,
        data: Mapping[str, str],
    ) -> PushSendResult:
        live = [t for t in tokens if t not in self.dead]
        self.sent.extend(
            {"token": t, "title": title, "body": body, "data": dict(data)} for t in live
        )
        return PushSendResult(
            attempted=len(tokens),
            sent=len(live),
            dead_tokens=tuple(t for t in tokens if t in self.dead),
        )
