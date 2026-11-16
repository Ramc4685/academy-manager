"""Referral programme (L9 C2): the daily sweep, the parent's card, the admin list.

``ProcessReferrals`` runs once a day per academy (``process_referrals`` job)
and does nothing at all while the programme is off. When on, it:

1. records a referral for every family that arrived with a referral code at
   or after ``effective_from``, keyed by the referred family so it happens
   once; the owner's credit, hold and expiry are frozen on the row. Only the
   code on the parent's own approved registration (an authenticated source)
   is ``pending``. A code seen only on a website inquiry (unauthenticated:
   anyone can submit it with a family's email) is ``needs_review`` and never
   auto-grants; the owner approves it (``ApproveReferral``) into ``pending``.
   A registration code replaces a not-yet-reviewed inquiry referral;
2. marks a pending referral qualified on the referred family's earliest
   invoice (of the owner's trigger kind) that is paid, above $0, not fully
   refunded and not disputed; due after the hold;
3. before granting, re-checks that invoice: if it has since been refunded,
   reversed (ACH return reopens it) or disputed, the qualification is
   cleared so a later good invoice can re-qualify, and nothing is granted;
4. grants due referrals: claims one of the referrer's yearly reward slots
   (unique per academy, so the cap holds under any concurrency; the year is
   the academy's local year), then writes each credit through
   ``create_if_absent`` with a deterministic ``(REFERRAL, <referral_id>:<role>)``
   source, which the unique ``academy_credit_source_unique`` index makes
   exactly-once on any retry or replay. Each credit is written against the
   parent id that family's invoices are billed under, so monthly billing
   spends it. A crash between steps resumes on the next run.

No clawback after a grant (owner decision). No email is sent from here; the
copy lives in ``composition/referral_emails.py`` awaiting owner sign-off.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo

from backend.v2.contexts.billing.domain.models import CreditLedgerEntry
from backend.v2.contexts.billing.domain.referral import (
    REFERRAL_CREDIT_SOURCE_TYPE,
    CreditRole,
    IneligibleReason,
    Referral,
    ReferralSource,
    credit_source_id,
    is_self_referral,
    new_referral_code,
    normalize_code,
    reward_key,
)
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.time import ensure_utc

ClaimOutcome = Literal["claimed", "taken", "lost"]

#: The admin list shows this many of the newest referrals.
ADMIN_LIST_LIMIT = 200


@dataclass(frozen=True)
class ReferralCandidate:
    """A family that arrived with a referral code."""

    referred_parent_id: str
    code: str
    source: ReferralSource
    source_id: str
    attributed_at: datetime
    emails: tuple[str | None, ...] = ()
    phones: tuple[str | None, ...] = ()


@dataclass(frozen=True)
class Household:
    """Every id, email and phone a parent's account answers to."""

    ids: frozenset[str]
    emails: tuple[str | None, ...] = ()
    phones: tuple[str | None, ...] = ()


@dataclass(frozen=True)
class FirstInvoice:
    """A paid, non-zero, not fully refunded, undisputed invoice."""

    invoice_id: str
    parent_id: str
    paid_at: datetime


class ReferralSettingsReader(Protocol):
    async def get(self) -> Any: ...


class ReferralStore(Protocol):
    async def family_statuses(self) -> dict[str, str]:
        """Referred parent id -> the status of that family's referral."""
        ...

    async def insert_if_absent(self, referral: Referral) -> bool: ...

    async def replace_unreviewed(self, referral: Referral) -> bool:
        """Overwrite the family's row only while it is ``needs_review``."""
        ...

    async def approve(self, referral_id: str, *, actor_id: str, now: datetime) -> bool:
        """``needs_review`` -> ``pending``; ``False`` if it was not awaiting review."""
        ...

    async def get(self, referral_id: str) -> Referral | None: ...

    async def list_pending(self) -> list[Referral]: ...

    async def list_recent(self, limit: int) -> list[Referral]: ...

    async def count_granted_for(self, referrer_parent_id: str) -> int: ...

    async def mark_qualified(
        self,
        referral_id: str,
        *,
        invoice_id: str,
        qualified_at: datetime,
        due_at: datetime,
        now: datetime,
    ) -> None: ...

    async def clear_qualification(self, referral_id: str, *, now: datetime) -> None:
        """A pending, not-yet-granted referral forgets its invoice, hold and
        slot, so a later good invoice can qualify it again."""
        ...

    async def mark_ineligible(
        self, referral_id: str, reason: IneligibleReason, *, now: datetime
    ) -> None:
        """Only a pending referral with no reward slot claimed."""
        ...

    async def count_reward_slots(self, referrer_parent_id: str, year: int) -> int: ...

    async def claim_reward_slot(
        self, referral_id: str, *, key: str, year: int, now: datetime
    ) -> ClaimOutcome:
        """``taken``: another referral holds the slot; ``lost``: this referral
        is no longer pending without a slot."""
        ...

    async def mark_granted(
        self,
        referral_id: str,
        *,
        referrer_credit_id: str | None,
        referred_credit_id: str | None,
        now: datetime,
    ) -> None: ...


class ReferralCodeStore(Protocol):
    async def code_for(self, parent_id: str) -> str | None: ...

    async def insert(self, parent_id: str, code: str, *, now: datetime) -> bool:
        """``False`` when the parent already has a code or the code is taken."""
        ...

    async def parent_for(self, code: str) -> str | None: ...


class ReferralSources(Protocol):
    async def candidates(self, *, since: datetime) -> list[ReferralCandidate]: ...

    async def household(self, parent_id: str) -> Household: ...

    async def has_invoice_before(self, parent_ids: frozenset[str], at: datetime) -> bool: ...

    async def first_paid_invoice(
        self, parent_ids: frozenset[str], *, monthly_only: bool
    ) -> FirstInvoice | None: ...

    async def invoice_still_paid(self, invoice_id: str) -> bool:
        """Paid, above $0, not fully refunded and no open or lost dispute."""
        ...

    async def billing_parent_id(self, parent_ids: frozenset[str]) -> str | None:
        """The id this family's latest enrollment (else non-void invoice) is
        billed under, which is what monthly billing spends credit for."""
        ...

    async def display_names(self, parent_ids: set[str]) -> dict[str, str]: ...


class ReferralCredits(Protocol):
    async def create_if_absent(self, entry: CreditLedgerEntry) -> bool: ...

    async def find_by_source(
        self, *, source_type: str, source_id: str
    ) -> CreditLedgerEntry | None: ...


@dataclass
class ReferralRunResult:
    recorded: int = 0
    qualified: int = 0
    granted: int = 0


async def _utc_zone(_academy_id: str) -> str:
    return "UTC"


class ProcessReferrals:
    def __init__(
        self,
        *,
        settings: ReferralSettingsReader,
        referrals: ReferralStore,
        codes: ReferralCodeStore,
        sources: ReferralSources,
        credits: ReferralCredits,
        academy_id: Callable[[], str],
        timezone_for: Callable[[str], Awaitable[str]] = _utc_zone,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._settings = settings
        self._referrals = referrals
        self._codes = codes
        self._sources = sources
        self._credits = credits
        self._academy_id = academy_id
        self._timezone_for = timezone_for
        self._now = clock

    async def execute(self) -> ReferralRunResult:
        result = ReferralRunResult()
        program = (await self._settings.get()).referral_program
        if not program.enabled:
            return result
        now = self._now()
        if program.effective_from is not None:
            await self._record(program, ensure_utc(program.effective_from), now, result)
        for referral in await self._referrals.list_pending():
            await self._advance(referral, program, now, result)
        return result

    async def advance_one(self, referral_id: str) -> ReferralRunResult:
        """Qualify and grant one pending referral now, by the same path the
        daily run takes (so still exactly-once and within the cap)."""
        result = ReferralRunResult()
        program = (await self._settings.get()).referral_program
        referral = await self._referrals.get(referral_id)
        if program.enabled and referral is not None and referral.status == "pending":
            await self._advance(referral, program, self._now(), result)
        return result

    async def _record(
        self, program: Any, since: datetime, now: datetime, result: ReferralRunResult
    ) -> None:
        statuses = await self._referrals.family_statuses()
        found = await self._sources.candidates(since=since)
        codes_by_family: dict[str, set[str]] = defaultdict(set)
        for candidate in found:
            codes_by_family[candidate.referred_parent_id].add(normalize_code(candidate.code) or "")
        # Registrations first, so the authenticated code wins over an inquiry's.
        handled: set[str] = set()
        for candidate in sorted(found, key=lambda c: c.source != "application"):
            family = candidate.referred_parent_id
            if family in handled:
                continue
            existing = statuses.get(family)
            # A family with a row is settled, except an unreviewed inquiry,
            # which a registration may still replace. Skip before any lookup.
            if existing is not None and not (
                existing == "needs_review" and candidate.source == "application"
            ):
                continue
            handled.add(family)
            referral = await self._referral_for(candidate, codes_by_family[family], program, now)
            if existing is not None:
                recorded = await self._referrals.replace_unreviewed(referral)
            else:
                recorded = await self._referrals.insert_if_absent(referral)
            result.recorded += int(recorded)

    async def _referral_for(
        self, candidate: ReferralCandidate, family_codes: set[str], program: Any, now: datetime
    ) -> Referral:
        code = normalize_code(candidate.code) or ""
        referrer = await self._codes.parent_for(code)
        reason: IneligibleReason | None = None
        if referrer is None:
            reason = "unknown_code"
        else:
            mine = await self._sources.household(referrer)
            theirs = await self._sources.household(candidate.referred_parent_id)
            if is_self_referral(
                referrer_ids=mine.ids,
                referrer_emails=mine.emails,
                referrer_phones=mine.phones,
                referred_ids=theirs.ids,
                referred_emails=(*candidate.emails, *theirs.emails),
                referred_phones=(*candidate.phones, *theirs.phones),
            ):
                reason = "self_referral"
            elif await self._sources.has_invoice_before(
                theirs.ids, ensure_utc(candidate.attributed_at)
            ):
                reason = "existing_family"
        status = (
            "ineligible"
            if reason
            else "pending"
            if candidate.source == "application"
            else "needs_review"
        )
        return Referral(
            referral_id=str(new_ulid()),
            academy_id=self._academy_id(),
            referral_code=code,
            referrer_parent_id=referrer,
            referred_parent_id=candidate.referred_parent_id,
            source=candidate.source,
            source_id=candidate.source_id,
            attributed_at=ensure_utc(candidate.attributed_at),
            competing_codes=tuple(sorted(c for c in family_codes if c and c != code)),
            status=status,
            reason=reason,
            referrer_credit_cents=program.referrer_credit_cents,
            referred_credit_cents=program.referred_credit_cents,
            hold_days=program.hold_days,
            credit_expiry_days=program.credit_expiry_days,
            created_at=now,
            updated_at=now,
        )

    async def _advance(
        self, referral: Referral, program: Any, now: datetime, result: ReferralRunResult
    ) -> None:
        if referral.qualified_invoice_id is not None and not await self._sources.invoice_still_paid(
            referral.qualified_invoice_id
        ):
            # Refunded, reversed or disputed since it qualified: start over.
            await self._referrals.clear_qualification(referral.referral_id, now=now)
            referral = referral.model_copy(
                update={
                    "qualified_invoice_id": None,
                    "qualified_at": None,
                    "grant_due_at": None,
                    "reward_key": None,
                }
            )
        if referral.qualified_at is None:
            household = await self._sources.household(referral.referred_parent_id)
            first = await self._sources.first_paid_invoice(
                household.ids, monthly_only=program.trigger == "first_paid_monthly_invoice"
            )
            if first is None:
                return
            paid_at = ensure_utc(first.paid_at)
            due = paid_at + timedelta(days=referral.hold_days or 0)
            await self._referrals.mark_qualified(
                referral.referral_id,
                invoice_id=first.invoice_id,
                qualified_at=paid_at,
                due_at=due,
                now=now,
            )
            result.qualified += 1
            referral = referral.model_copy(
                update={
                    "qualified_invoice_id": first.invoice_id,
                    "qualified_at": paid_at,
                    "grant_due_at": due,
                }
            )
        if referral.grant_due_at is None or ensure_utc(referral.grant_due_at) > now:
            return
        if await self._grant(referral, program, now):
            result.granted += 1

    async def _grant(self, referral: Referral, program: Any, now: datetime) -> bool:
        referrer = referral.referrer_parent_id
        assert referrer is not None and referral.qualified_at is not None
        if referral.reward_key is None and not await self._claim_slot(
            referral, referrer, program, now
        ):
            return False
        referrer_household = await self._sources.household(referrer)
        referrer_account = await self._sources.billing_parent_id(referrer_household.ids)
        referred_household = await self._sources.household(referral.referred_parent_id)
        referred_account = await self._sources.billing_parent_id(referred_household.ids)
        referrer_credit = await self._credit(
            referral, "referrer", referrer_account or referrer, now
        )
        referred_credit = await self._credit(
            referral, "referred", referred_account or referral.referred_parent_id, now
        )
        await self._referrals.mark_granted(
            referral.referral_id,
            referrer_credit_id=referrer_credit,
            referred_credit_id=referred_credit,
            now=now,
        )
        return True

    async def _claim_slot(
        self, referral: Referral, referrer: str, program: Any, now: datetime
    ) -> bool:
        cap = int(program.max_rewards_per_referrer_per_year or 0)
        zone = ZoneInfo(await self._timezone_for(self._academy_id()))
        year = ensure_utc(referral.qualified_at or now).astimezone(zone).year
        for _ in range(cap + 2):
            taken = await self._referrals.count_reward_slots(referrer, year)
            if taken >= cap:
                await self._referrals.mark_ineligible(
                    referral.referral_id, "yearly_cap_reached", now=now
                )
                return False
            outcome = await self._referrals.claim_reward_slot(
                referral.referral_id, key=reward_key(referrer, year, taken + 1), year=year, now=now
            )
            if outcome == "claimed":
                return True
            if outcome == "lost":
                # A concurrent run of this same referral got there first.
                again = await self._referrals.get(referral.referral_id)
                return again is not None and again.status != "ineligible" and bool(again.reward_key)
        return False  # still racing; the next run tries again

    async def _credit(
        self, referral: Referral, role: CreditRole, parent_id: str, now: datetime
    ) -> str | None:
        amount = (
            referral.referrer_credit_cents if role == "referrer" else referral.referred_credit_cents
        )
        if not amount:
            return None
        source_id = credit_source_id(referral.referral_id, role)
        entry = CreditLedgerEntry(
            credit_id=str(new_ulid()),
            academy_id="",  # stamped by the tenant-scoped repository on write
            parent_id=parent_id,
            type="REFERRAL_CREDIT",
            status="APPROVED",
            amount_cents=amount,
            remaining_amount_cents=amount,
            reason=(
                f"Referral reward (code {referral.referral_code})"
                if role == "referrer"
                else "Welcome credit for joining through a referral"
            ),
            source_type=REFERRAL_CREDIT_SOURCE_TYPE,
            source_id=source_id,
            approved_by="referral_program",
            approved_at=now,
            expires_at=(
                now + timedelta(days=referral.credit_expiry_days)
                if referral.credit_expiry_days
                else None
            ),
            created_at=now,
            updated_at=now,
        )
        if await self._credits.create_if_absent(entry):
            return entry.credit_id
        existing = await self._credits.find_by_source(
            source_type=REFERRAL_CREDIT_SOURCE_TYPE, source_id=source_id
        )
        return existing.credit_id if existing else None


class ReferralNotReviewable(Exception):
    """The referral is not awaiting review, or the programme is off."""


class ApproveReferral:
    """Owner approves an inquiry-only referral: ``needs_review`` -> ``pending``
    (recording who and when on the row), then advances it at once, so a family
    that has already paid past the hold is credited now through the normal
    exactly-once, capped path; otherwise the daily run grants it later."""

    def __init__(
        self,
        *,
        settings: ReferralSettingsReader,
        referrals: ReferralStore,
        process: ProcessReferrals,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._settings = settings
        self._referrals = referrals
        self._process = process
        self._now = clock

    async def execute(self, referral_id: str, *, actor_id: str) -> Referral:
        if not (await self._settings.get()).referral_program.enabled:
            raise ReferralNotReviewable("The referral programme is off.")
        if not await self._referrals.approve(referral_id, actor_id=actor_id, now=self._now()):
            raise ReferralNotReviewable("This referral is not awaiting review.")
        await self._process.advance_one(referral_id)
        referral = await self._referrals.get(referral_id)
        assert referral is not None
        return referral


@dataclass(frozen=True)
class ParentReferralView:
    enabled: bool
    referral_code: str | None = None
    share_url: str | None = None
    rewards_earned: int = 0
    referrer_credit_cents: int | None = None
    referred_credit_cents: int | None = None


class GetParentReferral:
    """The parent's code (minted once, on first view while the programme is
    on), the link to share (the academy's own public page) and how many
    rewards they have earned. Off: nothing is read or minted."""

    def __init__(
        self,
        *,
        settings: ReferralSettingsReader,
        referrals: ReferralStore,
        codes: ReferralCodeStore,
        academy_id: Callable[[], str],
        base_url_for: Callable[[str], Awaitable[str]],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._settings = settings
        self._referrals = referrals
        self._codes = codes
        self._academy_id = academy_id
        self._base_url_for = base_url_for
        self._now = clock

    async def execute(self, parent_id: str) -> ParentReferralView:
        program = (await self._settings.get()).referral_program
        if not program.enabled:
            return ParentReferralView(enabled=False)
        code = await self._codes.code_for(parent_id)
        for _ in range(5):
            if code is not None:
                break
            await self._codes.insert(parent_id, new_referral_code(), now=self._now())
            code = await self._codes.code_for(parent_id)
        base = await self._base_url_for(self._academy_id())
        return ParentReferralView(
            enabled=True,
            referral_code=code,
            share_url=f"{base}/?ref={code}" if code else None,
            rewards_earned=await self._referrals.count_granted_for(parent_id),
            referrer_credit_cents=program.referrer_credit_cents,
            referred_credit_cents=program.referred_credit_cents,
        )


@dataclass(frozen=True)
class ReferralListRow:
    referral: Referral
    referrer_name: str | None
    referred_name: str | None


class ListReferrals:
    """Admin: the newest referrals with both families' names."""

    def __init__(self, *, referrals: ReferralStore, sources: ReferralSources) -> None:
        self._referrals = referrals
        self._sources = sources

    async def execute(self) -> list[ReferralListRow]:
        rows = await self._referrals.list_recent(ADMIN_LIST_LIMIT)
        ids = {r.referred_parent_id for r in rows} | {
            r.referrer_parent_id for r in rows if r.referrer_parent_id
        }
        names = await self._sources.display_names(ids) if ids else {}
        return [
            ReferralListRow(
                referral=r,
                referrer_name=names.get(r.referrer_parent_id or ""),
                referred_name=names.get(r.referred_parent_id),
            )
            for r in rows
        ]
