"""Lead nurture sequence (AI strategy Phase 3, C1): the daily job and the
owner's editor. Rules in ``domain/nurture.py``; README "Lead nurture".

``SendNurtureSteps`` runs once per academy per local day (``send_nurture_steps``
in ``main.py``) inside the academy's tenant scope. Every send goes through the
``NurtureNotifier`` port, which composition implements over the prospect send
path (``ProspectEmailer``: ``crm_contact:<id>`` recipient, ``ProspectOptOutGate``,
bounce suppression, unsubscribe footer) with category ``CAMPAIGN``, and every
send is claimed once per (inbox, step) through ``send_once``.

The CRM context imports no other context: the academy settings, the opt-out
store and the contact log are ports implemented in ``composition/nurture.py``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from functools import partial
from typing import Protocol

from backend.v2.contexts.crm.application.use_cases.send_pipeline_reply import (
    contact_log_parent_id,
)
from backend.v2.contexts.crm.domain.models import CrmContact
from backend.v2.contexts.crm.domain.nurture import (
    CANDIDATE_LOOKBACK,
    MAX_BODY_LENGTH,
    MAX_SUBJECT_LENGTH,
    MERGE_FIELDS,
    NURTURE_STEP_DAYS,
    NurtureSequence,
    NurtureStep,
    created_on,
    due_step,
    render_subject,
    render_text,
    stop_reason,
    validate_steps,
)
from backend.v2.shared.comms.claimed_send import (
    SendClaimRepository,
    SendResult,
    send_once,
    sent_count,
)
from backend.v2.shared.comms.mailbox import canonical_mailbox

#: Re-exported for the admin BFF, which may not import the domain directly.
__all__ = [
    "MAX_BODY_LENGTH",
    "MAX_SUBJECT_LENGTH",
    "MERGE_FIELDS",
    "NURTURE_STEP_DAYS",
    "ManageNurtureSequence",
    "NurtureSequence",
    "NurtureStep",
    "SendNurtureSteps",
]


class NurtureSettingsStore(Protocol):
    async def get(self, academy_id: str) -> NurtureSequence: ...

    async def save(
        self, academy_id: str, sequence: NurtureSequence, *, user_id: str, at: datetime
    ) -> None: ...


class NurtureCandidates(Protocol):
    async def list_nurture_candidates(self, *, created_since: datetime) -> list[CrmContact]: ...


class OptOutLookup(Protocol):
    async def is_opted_out(self, email: str) -> bool: ...


class ConversationLookup(Protocol):
    async def has_logged_contact(self, parent_id: str) -> bool: ...


class NurtureNotifier(Protocol):
    async def send_step(self, *, contact: CrmContact, step: NurtureStep) -> SendResult: ...

    async def example_values(self, academy_id: str) -> dict[str, str]:
        """The four merge values with an example class, for the editor's preview."""
        ...


class SendNurtureSteps:
    def __init__(
        self,
        *,
        settings: NurtureSettingsStore,
        contacts: NurtureCandidates,
        opt_outs: OptOutLookup,
        conversations: ConversationLookup,
        send_repo: SendClaimRepository,
        notifier: NurtureNotifier,
    ) -> None:
        self._settings = settings
        self._contacts = contacts
        self._opt_outs = opt_outs
        self._conversations = conversations
        self._send_repo = send_repo
        self._notifier = notifier

    async def execute(self, *, academy_id: str, local_now: datetime) -> int:
        """Run for ONE academy inside its tenant scope; ``local_now`` is on
        the academy's clock. Returns how many emails went out."""
        sequence = await self._settings.get(academy_id)
        steps = sequence.written_steps()
        if not sequence.enabled or sequence.enabled_at is None or not steps:
            return 0
        # Only leads that arrived after the switch went on: turning it on
        # never mails the academy's existing lead list.
        since = max(sequence.enabled_at, local_now.astimezone(UTC) - CANDIDATE_LOOKBACK)
        candidates = await self._contacts.list_nurture_candidates(created_since=since)
        results: list[SendResult | None] = []
        for inbox, contact in _one_per_inbox(candidates):
            if await self._stopped(contact):
                # Stops are permanent: spend the inbox's remaining steps so a
                # newer contact in the same inbox never restarts the sequence.
                for spent in steps:
                    await self._claim(academy_id, inbox, spent, _skip)
                continue
            step = due_step(
                steps, created_on=created_on(contact, local_now), today=local_now.date()
            )
            if step is None:
                continue
            results.append(
                await self._claim(
                    academy_id,
                    inbox,
                    step,
                    partial(self._notifier.send_step, contact=contact, step=step),
                )
            )
        return sent_count(results)

    async def _stopped(self, contact: CrmContact) -> bool:
        if stop_reason(contact) is not None or not contact.email:
            return True
        if await self._opt_outs.is_opted_out(contact.email):
            return True
        return await self._conversations.has_logged_contact(contact_log_parent_id(contact))

    async def _claim(
        self,
        academy_id: str,
        inbox: str,
        step: NurtureStep,
        send: Callable[[], Awaitable[SendResult]],
    ) -> SendResult | None:
        return await send_once(
            self._send_repo, academy_id=academy_id, subject_id=inbox, nudge_key=step.key, send=send
        )


async def _skip() -> SendResult:
    return "skipped"


def inbox_key(email: str | None) -> str | None:
    """The send-claim subject: one sequence per inbox, whichever contact in it
    is current. A hash, because the canonical mailbox is never stored."""
    mailbox = canonical_mailbox(email)
    return f"inbox:{hashlib.sha256(mailbox.encode()).hexdigest()[:32]}" if mailbox else None


def _one_per_inbox(contacts: list[CrmContact]) -> list[tuple[str, CrmContact]]:
    """The oldest contact per inbox, stopped or not. The public form files a
    second contact for a second child (or a ``+tag`` spelling of the same
    address); one inbox gets one sequence, and a stop on its oldest contact
    stops it for the inbox."""
    chosen: dict[str, CrmContact] = {}
    for contact in sorted(contacts, key=lambda c: (c.created_at, c.contact_id)):
        key = inbox_key(contact.email)
        if key and key not in chosen:
            chosen[key] = contact
    return list(chosen.items())


class ManageNurtureSequence:
    """The owner's editor: read, save (with the switch), and preview a step."""

    def __init__(
        self,
        settings: NurtureSettingsStore,
        notifier: NurtureNotifier,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._settings = settings
        self._notifier = notifier
        self._clock = clock

    async def get(self, academy_id: str) -> NurtureSequence:
        return await self._settings.get(academy_id)

    async def save(
        self, academy_id: str, *, enabled: bool, steps: list[NurtureStep], user_id: str
    ) -> NurtureSequence:
        current = await self._settings.get(academy_id)
        now = self._clock()
        # The audience starts when the switch goes on, so a re-save keeps the
        # original time and an off-then-on restarts it.
        enabled_at = (current.enabled_at if current.enabled else now) if enabled else None
        sequence = NurtureSequence(
            enabled=enabled, enabled_at=enabled_at, steps=validate_steps(steps)
        )
        await self._settings.save(academy_id, sequence, user_id=user_id, at=now)
        return sequence

    async def preview(self, academy_id: str, step: NurtureStep) -> tuple[str, str]:
        (checked,) = validate_steps([step])
        values = await self._notifier.example_values(academy_id)
        return render_subject(checked.subject, values), render_text(checked.body, values)
