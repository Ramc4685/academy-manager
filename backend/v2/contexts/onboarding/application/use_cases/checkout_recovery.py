"""Abandoned-checkout recovery (AI strategy Phase 1, item 3): templated.

Daily, academy-local job (``send_checkout_recovery_notices``, 10:10 local).
A registration application in ``CHECKOUT_EXPIRED`` (Stripe Checkout lapsed)
or ``ABANDONED`` (the 7-day draft TTL passed) gets ONE email inviting the
family back to finish, claimed per application on ``trial_nudge_sends``.

Only the parent's latest application qualifies: ``ABANDONED`` is stamped
when the parent returns and starts over (``StartApplication``), so a family
with a newer application has already come back and must not be nudged about
the old one. Applications stamped longer ago than ``RECOVERY_LOOKBACK`` are
left alone, so switching the job on never mails the whole history.

Respects ``notifications.trial_nudges_enabled`` like the trial nudges.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from functools import partial
from typing import Protocol

from backend.v2.contexts.onboarding.domain.models import Application
from backend.v2.shared.comms.claimed_send import SendClaimRepository, send_once
from backend.v2.shared.time import ensure_utc

RECOVERABLE_STATUSES: tuple[str, ...] = ("CHECKOUT_EXPIRED", "ABANDONED")
RECOVERY_LOOKBACK = timedelta(days=14)
CHECKOUT_RECOVERY_KEY = "checkout_recovery"


class RecoverableApplications(Protocol):
    async def list_by_status(self, statuses: list[str]) -> list[Application]: ...

    async def latest_for_parent(self, parent_user_id: str) -> Application | None: ...


class CheckoutRecoverySwitch(Protocol):
    async def is_enabled(self, academy_id: str) -> bool: ...


class CheckoutRecoveryNotifier(Protocol):
    """True when nothing is left to do (sent, or opted out); False to retry."""

    async def checkout_recovery(self, *, application: Application) -> bool: ...


class SendCheckoutRecoveryNotices:
    def __init__(
        self,
        *,
        applications: RecoverableApplications,
        send_repo: SendClaimRepository,
        notifier: CheckoutRecoveryNotifier,
        switch: CheckoutRecoverySwitch,
    ) -> None:
        self._applications = applications
        self._send_repo = send_repo
        self._notifier = notifier
        self._switch = switch

    async def execute(self, *, academy_id: str, local_now: datetime) -> int:
        """Run for ONE academy inside its tenant scope."""
        if not await self._switch.is_enabled(academy_id):
            return 0
        sent = 0
        for application in await self._applications.list_by_status(list(RECOVERABLE_STATUSES)):
            if ensure_utc(application.updated_at) < local_now - RECOVERY_LOOKBACK:
                continue
            latest = await self._applications.latest_for_parent(application.parent_user_id)
            if latest is None or latest.application_id != application.application_id:
                continue
            sent += await send_once(
                self._send_repo,
                academy_id=academy_id,
                subject_id=application.application_id,
                nudge_key=CHECKOUT_RECOVERY_KEY,
                send=partial(self._notifier.checkout_recovery, application=application),
            )
        return sent
