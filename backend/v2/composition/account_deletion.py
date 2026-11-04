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
from typing import Any

from backend.v2.contexts.billing.application.use_cases.remove_saved_payment_methods import (
    RemoveSavedPaymentMethods,
)
from backend.v2.contexts.billing.infrastructure.mongo_parent_billing_customer_repo import (
    MongoParentBillingCustomerRepository,
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
from backend.v2.contexts.identity.domain.account_deletion import AccountDeletionRequest
from backend.v2.contexts.identity.infrastructure.firebase_admin_adapter import (
    get_firebase_admin_adapter,
)
from backend.v2.contexts.identity.infrastructure.mongo_account_deletion_store import (
    MongoAccountDeletionStore,
)
from backend.v2.contexts.onboarding.infrastructure.mongo_application_repo import (
    MongoApplicationRepository,
)
from backend.v2.shared.observability.ops_alerts import capture_message
from backend.v2.shared.tenancy.context import tenant_scope

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
