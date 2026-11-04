"""Claim, send, mark: the one step every idempotent nudge job repeats.

``send_once`` is the loop body the trial nudges (``contexts/enrollment``) and
the checkout recovery notice (``contexts/onboarding``) share. It lives in
``shared`` because the two contexts may not import each other and the step is
the same: take the claim for ``(subject, nudge_key)``, send, then record the
result on the claim row. A send that raises or reports failure leaves a
``failed`` row for ``claim_digest_send``'s bounded re-claim on a later tick; a
claim already held sends nothing, which is what makes a second run a no-op.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

log = logging.getLogger(__name__)


class SendClaimRepository(Protocol):
    """One claim per ``(academy_id, subject_id, nudge_key)``, backed by
    ``claim_digest_send`` (composition/trial_nudges.py)."""

    async def try_claim(
        self, *, academy_id: str, subject_id: str, nudge_key: str
    ) -> dict[str, Any] | None: ...

    async def mark_sent(self, academy_id: str, send_id: str) -> None: ...

    async def mark_failed(self, academy_id: str, send_id: str, reason: str) -> None: ...


async def send_once(
    send_repo: SendClaimRepository,
    *,
    academy_id: str,
    subject_id: str,
    nudge_key: str,
    send: Callable[[], Awaitable[bool]],
) -> int:
    """Send ``nudge_key`` to ``subject_id`` at most once; 1 if sent now, else 0.

    ``send`` returns True when there is nothing left to do (delivered, or
    suppressed by the recipient's own choice) and False when it is worth
    trying again later.
    """
    claim = await send_repo.try_claim(
        academy_id=academy_id, subject_id=subject_id, nudge_key=nudge_key
    )
    if claim is None:
        return 0
    try:
        done = await send()
    except Exception:
        log.exception("nudge_send_failed", extra={"nudge_key": nudge_key, "subject_id": subject_id})
        done = False
    if not done:
        await send_repo.mark_failed(academy_id, claim["send_id"], "send_failed")
        return 0
    await send_repo.mark_sent(academy_id, claim["send_id"])
    return 1
