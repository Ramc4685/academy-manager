"""Abandoned-checkout recovery (AI strategy Phase 1, item 3): templated.

Daily, academy-local job (``send_checkout_recovery_notices``, 10:10 local).
A registration application the family walked away from gets ONE email
inviting them back, claimed per application on ``trial_nudge_sends``:

* ``CHECKOUT_EXPIRED``: Stripe Checkout lapsed after the parent reached it;
* a ``DRAFT`` past its 7-day TTL (``Application.is_expired``): the wizard was
  started and never finished. (``ABANDONED`` is not a candidate: it is
  stamped only by ``StartApplication`` at the moment the parent comes back
  and a newer application is minted, so it is never the parent's latest.)

Only the parent's latest application qualifies, so a family that has since
started over or registered is never nudged about the old one. Neither state
can be resumed (``StartApplication`` retires it and mints a fresh draft), so
the email says "start again", not "pick up where you left off". Applications
touched longer ago than ``RECOVERY_LOOKBACK`` are left alone, so switching
the job on never mails the whole history.

Respects ``notifications.trial_nudges_enabled`` like the trial nudges.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from functools import partial
from typing import Protocol

from backend.v2.contexts.onboarding.domain.models import Application
from backend.v2.shared.comms.claimed_send import (
    SendClaimRepository,
    SendResult,
    send_once,
    sent_count,
)
from backend.v2.shared.time import ensure_utc

RECOVERABLE_STATUSES: tuple[str, ...] = ("CHECKOUT_EXPIRED", "DRAFT")
RECOVERY_LOOKBACK = timedelta(days=14)
CHECKOUT_RECOVERY_KEY = "checkout_recovery"


class RecoverableApplications(Protocol):
    async def list_by_status(self, statuses: list[str]) -> list[Application]: ...

    async def latest_for_parent(self, parent_user_id: str) -> Application | None: ...


class CheckoutRecoverySwitch(Protocol):
    async def is_enabled(self, academy_id: str) -> bool: ...


class CheckoutRecoveryNotifier(Protocol):
    async def checkout_recovery(self, *, application: Application) -> SendResult: ...


def is_recoverable(application: Application, now: datetime) -> bool:
    if application.status == "CHECKOUT_EXPIRED":
        return True
    return application.status == "DRAFT" and application.is_expired(now)


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
        results: list[SendResult | None] = []
        for application in await self._applications.list_by_status(list(RECOVERABLE_STATUSES)):
            if not is_recoverable(application, local_now):
                continue
            if ensure_utc(application.updated_at) < local_now - RECOVERY_LOOKBACK:
                continue
            latest = await self._applications.latest_for_parent(application.parent_user_id)
            if latest is None or latest.application_id != application.application_id:
                continue
            results.append(
                await send_once(
                    self._send_repo,
                    academy_id=academy_id,
                    subject_id=application.application_id,
                    nudge_key=CHECKOUT_RECOVERY_KEY,
                    send=partial(self._notifier.checkout_recovery, application=application),
                )
            )
        return sent_count(results)
