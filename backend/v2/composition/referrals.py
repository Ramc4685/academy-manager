"""Composition for the referral programme (L9 C2).

Every repository resolves the tenant at execution time (request scope, or the
daily job's ``tenant_scope``), so nothing tenant-specific is captured here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.v2.composition import referral_emails
from backend.v2.composition.academy_links import academy_frontend_base_url_lookup
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
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import MongoAcademyRepository
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository
from backend.v2.shared.tenancy import current_academy_id
from backend.v2.shared.time.academy_timezone import (
    academy_timezone_lookup,
    resolve_academy_clock_timezone,
)


@dataclass(frozen=True)
class ReferralProgram:
    """What the admin and parent referral routes and the daily job read off
    ``app.state.referrals``."""

    process: ProcessReferrals
    parent_view: GetParentReferral
    admin_list: ListReferrals
    approve: ApproveReferral
    settings: MongoBillingSettingsRepository
    academies: MongoAcademyRepository

    async def email_preview(self) -> list[referral_emails.ReferralEmail]:
        """The two messages with sample values; never sends."""
        program = (await self.settings.get()).referral_program
        academy = await self.academies.find_by_id(current_academy_id()) or {}
        return referral_emails.preview(
            academy_name=str(academy.get("name") or "your academy"),
            referrer_credit_cents=program.referrer_credit_cents or 0,
            referred_credit_cents=program.referred_credit_cents or 0,
            currency=str(academy.get("currency") or "usd"),
        )


def compose_referrals(db: Any, *, frontend_url: str | None) -> ReferralProgram:
    settings = MongoBillingSettingsRepository(db)
    referrals = MongoReferralRepository(db)
    codes = MongoReferralCodeRepository(db)
    sources = MongoReferralSources(db, users=MongoUserRepository(db))
    zone_reader = academy_timezone_lookup(db)

    async def timezone_for(academy_id: str) -> str:
        return await resolve_academy_clock_timezone(zone_reader, academy_id)

    process = ProcessReferrals(
        settings=settings,
        referrals=referrals,
        codes=codes,
        sources=sources,
        credits=MongoCreditLedgerRepository(db),
        academy_id=current_academy_id,
        timezone_for=timezone_for,
    )
    return ReferralProgram(
        process=process,
        approve=ApproveReferral(settings=settings, referrals=referrals, process=process),
        parent_view=GetParentReferral(
            settings=settings,
            referrals=referrals,
            codes=codes,
            academy_id=current_academy_id,
            base_url_for=academy_frontend_base_url_lookup(db, frontend_url=frontend_url),
        ),
        admin_list=ListReferrals(referrals=referrals, sources=sources),
        settings=settings,
        academies=MongoAcademyRepository(db),
    )
