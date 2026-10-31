"""Owner daily brief orchestration: one brief per academy, to its owners.

``main.py`` owns the cron job, the 30-minute lease and the send port; this
module owns the per-academy loop so it can be tested against a real Mongo.

Recipients:

* every academy's brief goes to that academy's active owners
  (``academy_memberships`` role ``owner``, status ``active``, resolved to
  emails by ``MongoAudienceResolver`` inside the academy's tenant scope);
* the one exception is the house academy (BLNO): when ``OWNER_BRIEF_EMAIL``
  or ``OPS_ALERT_EMAIL`` is set it keeps receiving its brief at exactly that
  address, as it did before briefs were per academy. Those env addresses
  never receive any other academy's brief.

Each academy runs in its own ``try``: one academy failing (a bad row, a
provider error) is logged and reported to Sentry, and the loop moves on.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.contexts.communications.application.ports import (
    EmailSendPort,
    ResolvedRecipient,
)
from backend.v2.contexts.communications.domain.models import AcademyAudience
from backend.v2.contexts.communications.infrastructure.mongo_audience_resolver import (
    MongoAudienceResolver,
)
from backend.v2.shared.observability.ops_alerts import capture_message
from backend.v2.shared.observability.owner_daily_brief import (
    collect_owner_daily_brief,
    render_owner_daily_brief,
)
from backend.v2.shared.tenancy.context import tenant_scope

log = logging.getLogger(__name__)

#: The identity the house academy's env-addressed brief has always carried.
HOUSE_RECIPIENT_USER_ID = "owner-brief"
HOUSE_RECIPIENT_DISPLAY_NAME = "Owner"


@dataclass(frozen=True)
class OwnerBriefRunSummary:
    academies: int = 0
    sent: int = 0
    send_failed: int = 0
    skipped_no_recipient: int = 0
    failed: int = 0


async def resolve_owner_brief_recipients(
    db: AsyncIOMotorDatabase[Any],
    *,
    academy_id: str,
    house_academy_id: str | None,
    override_email: str | None,
) -> list[ResolvedRecipient]:
    """Who receives ``academy_id``'s brief. Call inside its tenant scope."""
    override = (override_email or "").strip()
    if override and house_academy_id and academy_id == house_academy_id:
        return [
            ResolvedRecipient(
                user_id=HOUSE_RECIPIENT_USER_ID,
                email=override,
                display_name=HOUSE_RECIPIENT_DISPLAY_NAME,
            )
        ]
    owners = await MongoAudienceResolver(db).resolve_academy_audience(AcademyAudience(role="owner"))
    recipients: list[ResolvedRecipient] = []
    seen: set[str] = set()
    for owner in owners:
        email = (owner.email or "").strip()
        if not email or email.lower() in seen:
            continue
        seen.add(email.lower())
        recipients.append(owner)
    return recipients


async def send_owner_daily_briefs(
    db: AsyncIOMotorDatabase[Any],
    *,
    sender: EmailSendPort,
    academy_ids: Iterable[str],
    house_academy_id: str | None,
    override_email: str | None,
    now: datetime,
) -> OwnerBriefRunSummary:
    """Collect, address and send one brief per academy.

    ``now`` must be on the academy's own clock (the scheduler passes each
    academy's local now, Settings Phase 4): the subject's date label is taken
    from it verbatim.
    """
    academies = sent = send_failed = skipped = failed = 0
    for academy_id in academy_ids:
        academies += 1
        try:
            with tenant_scope(academy_id):
                recipients = await resolve_owner_brief_recipients(
                    db,
                    academy_id=academy_id,
                    house_academy_id=house_academy_id,
                    override_email=override_email,
                )
                if not recipients:
                    skipped += 1
                    log.info("owner_brief_skipped_no_recipient academy_id=%s", academy_id)
                    continue
                brief = await collect_owner_daily_brief(db, academy_id=academy_id, now=now)
                subject, body = render_owner_daily_brief(brief)
                for recipient in recipients:
                    outcome = await sender.send(recipient=recipient, subject=subject, body=body)
                    extra = {
                        "academy_id": academy_id,
                        "recipient_user_id": recipient.user_id,
                        "ok": bool(getattr(outcome, "ok", False)),
                        "failed_reason": getattr(outcome, "failed_reason", None),
                        "new_enrollments": brief.new_enrollments,
                        "departures": brief.departures_total,
                        "approvals_waiting": brief.approvals_waiting,
                        "payments_failed": brief.payments_failed,
                        "waivers_missing": brief.waivers_missing,
                        "emails_undeliverable": brief.emails_undeliverable,
                    }
                    if extra["ok"]:
                        sent += 1
                        log.info("owner_brief_processed", extra=extra)
                    else:
                        # Resend never raises — a rejected send comes back as
                        # SendOutcome(ok=False) — so report it or it vanishes.
                        send_failed += 1
                        log.error("owner_brief_send_failed", extra=extra)
                        capture_message(
                            f"Owner daily brief send failed for academy {academy_id}: "
                            f"{extra['failed_reason']}"
                        )
        except Exception as exc:  # one academy never stops the rest
            failed += 1
            log.exception("owner_brief_academy_failed academy_id=%s", academy_id)
            capture_message(f"Owner daily brief failed for academy {academy_id}: {exc}")
    return OwnerBriefRunSummary(
        academies=academies,
        sent=sent,
        send_failed=send_failed,
        skipped_no_recipient=skipped,
        failed=failed,
    )
