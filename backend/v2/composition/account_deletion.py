"""Wire the self-service account-deletion executor (mobile M5, D3).

Identity owns the job (``ExecuteAccountDeletions``) but may not import other
contexts, so each context's share is an ``AccountErasureStep`` built here from
that context's own use cases and repositories. Steps run per academy inside
``tenant_scope``; each is idempotent so a failed run is simply repeated.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

from backend.v2.contexts.billing.application.use_cases.pause_family_autopay import (
    NothingToPause,
    PauseFamilyAutopay,
)
from backend.v2.contexts.billing.application.use_cases.remove_saved_payment_methods import (
    RemoveSavedPaymentMethods,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_audit_log import (
    MongoBillingAuditLogRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_parent_billing_customer_repo import (
    MongoParentBillingCustomerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_student_billing_enrollment_repo import (
    MongoStudentBillingEnrollmentRepository,
)
from backend.v2.contexts.communications.infrastructure.mongo_account_erasure import (
    MongoCommunicationsErasure,
)
from backend.v2.contexts.crm.infrastructure.mongo_family_erasure import MongoFamilyErasure
from backend.v2.contexts.enrollment.application.use_cases.stop_all_classes import (
    StopAllClasses,
    StopAllClassesCommand,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)
from backend.v2.contexts.identity.application.use_cases.execute_account_deletions import (
    ExecuteAccountDeletions,
)
from backend.v2.contexts.identity.application.use_cases.send_login_invite import (
    AcademyNameLookup,
    InviteEmailPort,
)
from backend.v2.contexts.identity.domain.account_deletion import AccountDeletionRequest
from backend.v2.contexts.identity.infrastructure.firebase_admin_adapter import (
    get_firebase_admin_adapter,
)
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import MongoAcademyRepository
from backend.v2.contexts.identity.infrastructure.mongo_account_deletion_store import (
    MongoAccountDeletionStore,
)
from backend.v2.contexts.onboarding.infrastructure.mongo_application_repo import (
    MongoApplicationRepository,
)
from backend.v2.shared.comms.email_brand import branded_as
from backend.v2.shared.comms.email_theme import INK, MUTED, shell
from backend.v2.shared.idempotency.mongo_store import MongoIdempotencyStore
from backend.v2.shared.observability.ops_alerts import capture_message
from backend.v2.shared.tenancy.context import tenant_scope
from backend.v2.shared.time.academy_timezone import (
    AcademyTimezoneReader,
    academy_timezone_lookup,
    resolve_academy_clock_timezone,
)

log = logging.getLogger(__name__)

SYSTEM_ACTOR = "system:account-deletion"


@dataclass
class FamilyErasureStep:
    """Drop every class (no money moves: ``adjustment``), then anonymise the
    children and delete the family's CRM records, unless another guardian with
    an active account in that academy still looks after the children."""

    stop_all_classes: StopAllClasses
    students: MongoStudentRepository
    family: MongoFamilyErasure
    applications: MongoApplicationRepository
    identity: MongoAccountDeletionStore
    name: str = "family"

    async def erase(self, request: AccountDeletionRequest, *, now: datetime) -> None:
        parent_ids = list(request.aliases)
        for academy_id in request.academy_ids:
            with tenant_scope(academy_id):
                children = {
                    s.student_id: s
                    for parent_id in parent_ids
                    for s in await self.students.list_for_parent(parent_id)
                }
                for student_id in children:
                    result = await self.stop_all_classes.execute(
                        StopAllClassesCommand(
                            student_id=student_id,
                            effective_at=now,
                            outcome="adjustment",
                            reason="Parent deleted their account",
                            actor_id=SYSTEM_ACTOR,
                        )
                    )
                    if result.failed_count:
                        raise RuntimeError(f"could not drop every class for {student_id}")
                guardians = await self.family.guardian_emails(
                    academy_id=academy_id, parent_ids=parent_ids
                )
                if await self.identity.has_active_account(academy_id=academy_id, emails=guardians):
                    # Owner decision 3: the children stay with that guardian; an
                    # admin re-homes the family (students still name this parent).
                    capture_message(
                        f"Account deletion {request.request_id}: academy {academy_id} has another "
                        "guardian with an active account; children kept, re-home the family",
                        level="warning",
                    )
                    continue
                for student_id in children:
                    await self.students.anonymise(student_id, now=now)
                await self.family.erase_family(academy_id=academy_id, parent_ids=parent_ids)
                await self.applications.delete_for_parent(
                    academy_id=academy_id, parent_user_ids=parent_ids
                )


@dataclass
class BillingErasureStep:
    remove_cards: RemoveSavedPaymentMethods
    name: str = "billing"

    async def erase(self, request: AccountDeletionRequest, *, now: datetime) -> None:
        for academy_id in request.academy_ids:
            with tenant_scope(academy_id):
                await self.remove_cards.execute(parent_ids=request.aliases)


@dataclass
class CommunicationsErasureStep:
    comms: MongoCommunicationsErasure
    name: str = "communications"

    async def erase(self, request: AccountDeletionRequest, *, now: datetime) -> None:
        for academy_id in request.academy_ids:
            await self.comms.erase(academy_id=academy_id, user_ids=request.aliases)


@dataclass
class StopServicesOnDeletionRequest:
    """Run at request time, not after the 14-day grace period: a locked-out
    parent must not keep a child on the roster or a card on autopay.

    Dropping classes goes through ``StopAllClasses`` (the executor's own path),
    whose withdrawals run billing sync: later invoices are voided and each
    enrollment's autopay is disabled. ``PauseFamilyAutopay`` then catches any
    autopay left active on an enrollment that was no longer live. Both are
    idempotent, so the executor repeating the drop later is harmless.
    """

    stop_all_classes: StopAllClasses
    students: MongoStudentRepository
    pause_autopay: PauseFamilyAutopay
    sender: InviteEmailPort
    academies: AcademyNameLookup
    timezones: AcademyTimezoneReader

    async def on_requested(self, request: AccountDeletionRequest, *, fresh: bool) -> None:
        failures: list[str] = []
        for academy_id in request.academy_ids:
            with tenant_scope(academy_id):
                children = {
                    s.student_id
                    for parent_id in request.aliases
                    for s in await self.students.list_for_parent(parent_id)
                }
                for student_id in children:
                    result = await self.stop_all_classes.execute(
                        StopAllClassesCommand(
                            student_id=student_id,
                            effective_at=request.requested_at,
                            outcome="adjustment",
                            reason="Parent requested account deletion",
                            actor_id=SYSTEM_ACTOR,
                            # The confirmation below is the family's one message.
                            notify_family=False,
                        )
                    )
                    if result.failed_count:
                        failures.append(student_id)
                for parent_id in request.aliases:
                    try:
                        await self.pause_autopay.execute(
                            academy_id=academy_id,
                            parent_id=parent_id,
                            actor_id=SYSTEM_ACTOR,
                            reason="Parent requested account deletion",
                            request_id=request.request_id,
                        )
                    except NothingToPause:
                        pass
        # Checked before the email: it says the classes were dropped, so it
        # must not go out when one was not. The retry (fresh=False) never
        # sends; the executor drops again at day 14.
        if failures:
            raise RuntimeError(f"could not drop every class for {', '.join(failures)}")
        if fresh:
            await self._send_confirmation(request)

    async def _send_confirmation(self, request: AccountDeletionRequest) -> None:
        if not request.email:
            return
        academy_name = "your academy"
        erase_on = request.execute_after
        if request.academy_ids:
            first = request.academy_ids[0]
            academy_name = await self.academies.get_academy_name(first) or academy_name
            tz = await resolve_academy_clock_timezone(self.timezones, first)
            erase_on = erase_on.astimezone(ZoneInfo(tz))
        outcome = await self.sender.send_invite_email(
            user_id=request.user_id,
            email=request.email,
            display_name=request.email,
            subject=f"Your {academy_name} account is being deleted",
            body=_deletion_confirmation_body(academy_name=academy_name, erase_on=erase_on),
        )
        if not outcome.ok:
            raise RuntimeError(f"confirmation email not sent: {outcome.failed_reason}")


#: shortcut: mirrors frontend/lib/brand.ts `supportEmail`; move to settings if it
#: ever varies by deployment. Restore is support-only, so the email points here.
PLATFORM_SUPPORT_EMAIL = "support@marvy-labs.com"


def _deletion_confirmation_body(*, academy_name: str, erase_on: datetime) -> str:
    safe_name = escape(academy_name)
    support = escape(PLATFORM_SUPPORT_EMAIL)
    inner = (
        f'<h2 style="color:{INK};font-size:20px;margin:0 0 12px;">'
        f"We received your request to delete your account</h2>"
        f"<p>Your {safe_name} account is now locked. Your children have been taken off "
        f"their upcoming classes and automatic payments have stopped.</p>"
        f"<p>Your personal information will be permanently erased on "
        f"{erase_on:%B} {erase_on.day}, {erase_on.year}. Until then, email {support} "
        f"if you want to keep your account. Restoring it brings back your sign-in, not "
        f"your children&rsquo;s classes or automatic payments.</p>"
        f'<p style="color:{MUTED};font-size:13px;">If you didn&rsquo;t ask for this, '
        f"email {support} right away.</p>"
    )
    return shell(brand=branded_as(None, academy_name), inner_html=inner)


class _FirebaseRemover:
    async def delete_user(self, uid: str) -> None:
        await get_firebase_admin_adapter().delete_user_if_present(uid)


def compose_execute_account_deletions(
    db: Any, *, stop_all_classes: StopAllClasses, stripe: Any, firebase: Any = None
) -> ExecuteAccountDeletions:
    store = MongoAccountDeletionStore(db)
    return ExecuteAccountDeletions(
        store=store,
        steps=(
            # Order matters: dropping classes runs billing_sync (voids future
            # invoices) before the cards it might have charged are removed.
            FamilyErasureStep(
                stop_all_classes=stop_all_classes,
                students=MongoStudentRepository(db),
                family=MongoFamilyErasure(db),
                applications=MongoApplicationRepository(db),
                identity=store,
            ),
            BillingErasureStep(
                remove_cards=RemoveSavedPaymentMethods(
                    customers=MongoParentBillingCustomerRepository(db), stripe=stripe
                )
            ),
            CommunicationsErasureStep(comms=MongoCommunicationsErasure(db)),
        ),
        firebase=firebase or _FirebaseRemover(),
    )


def compose_deletion_request_follow_up(
    db: Any, *, stop_all_classes: StopAllClasses, sender: InviteEmailPort
) -> StopServicesOnDeletionRequest:
    return StopServicesOnDeletionRequest(
        stop_all_classes=stop_all_classes,
        students=MongoStudentRepository(db),
        pause_autopay=PauseFamilyAutopay(
            enrollments=MongoStudentBillingEnrollmentRepository(db),
            audit=MongoBillingAuditLogRepository(db),
            idempotency=MongoIdempotencyStore(db),
        ),
        sender=sender,
        academies=MongoAcademyRepository(db),
        timezones=academy_timezone_lookup(db),
    )
