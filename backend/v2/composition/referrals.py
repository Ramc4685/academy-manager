"""Composition for the referral programme (L9 C2).

Every repository resolves the tenant at execution time (request scope, or the
daily job's ``tenant_scope``), so nothing tenant-specific is captured here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.v2.composition import referral_emails
from backend.v2.contexts.billing.application.use_cases.referrals import (
    ApproveReferral,
    GetParentReferral,
    ListReferrals,
    ProcessReferrals,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_credit_ledger_repo import (
    MongoCreditLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_referrals import (
    MongoReferralCodeRepository,
    MongoReferralRepository,
    MongoReferralSources,
)
from backend.v2.shared.tenancy import current_academy_id


@dataclass(frozen=True)
class ReferralProgram:
    """What the admin and parent referral routes and the daily job read off
    ``app.state.referrals``."""

    process: ProcessReferrals
    parent_view: GetParentReferral
    admin_list: ListReferrals
    approve: ApproveReferral
    db: Any

    async def email_preview(self) -> list[referral_emails.ReferralEmail]:
        """The two messages with sample values; never sends."""
        program = (await MongoBillingSettingsRepository(self.db).get()).referral_program
        academy = await self.db["academies"].find_one(
            {"academy_id": current_academy_id()}, {"name": 1}
        )
        return referral_emails.preview(
            academy_name=str((academy or {}).get("name") or "your academy"),
            referrer_credit_cents=program.referrer_credit_cents or 0,
            referred_credit_cents=program.referred_credit_cents or 0,
        )


def compose_referrals(db: Any) -> ReferralProgram:
    settings = MongoBillingSettingsRepository(db)
    referrals = MongoReferralRepository(db)
    codes = MongoReferralCodeRepository(db)
    sources = MongoReferralSources(db)
    process = ProcessReferrals(
        settings=settings,
        referrals=referrals,
        codes=codes,
        sources=sources,
        credits=MongoCreditLedgerRepository(db),
        academy_id=current_academy_id,
    )
    return ReferralProgram(
        process=process,
        approve=ApproveReferral(settings=settings, referrals=referrals, process=process),
        parent_view=GetParentReferral(settings=settings, referrals=referrals, codes=codes),
        admin_list=ListReferrals(referrals=referrals, sources=sources),
        db=db,
    )
