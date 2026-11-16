"""Settings -> Billing rules -> Family offers: one read and one audited write (L9 C1).

Two blocks on ``billing_settings``: the referral programme (values stored;
switching it on is refused until C2 builds its logic) and the automatic sibling discount (applied by the
monthly resolver). The owner chooses whether to use each and sets every
value; there are no business values in code. The UI component holds the
form's starting values.

A change applies to invoices generated afterwards only: the monthly resolver
freezes each enrollment-month's sibling decision the first time it prices it
and never touches an existing invoice.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final, Protocol

from pydantic import BaseModel, ValidationError

from backend.v2.contexts.billing.application.use_cases.billing_rules import (
    BillingRulesValidationError,
)
from backend.v2.contexts.billing.application.use_cases.money_setting_audit import (
    MoneySettingAction,
    RecordMoneySettingChange,
)
from backend.v2.contexts.billing.domain.billing_settings import (
    SIBLING_REQUIRED_ON_ENABLE,
    ReferralProgram,
    SiblingDiscount,
)

#: Inclusive bounds, checked before anything is written. A field may be left
#: unset while its block is off; switching the sibling discount on requires
#: every field in ``SIBLING_REQUIRED_ON_ENABLE``.
REFERRAL_BOUNDS: Final[Mapping[str, tuple[int, int]]] = {
    "referrer_credit_cents": (1, 50_000),
    "referred_credit_cents": (1, 50_000),
    "hold_days": (0, 60),
    "max_rewards_per_referrer_per_year": (1, 100),
    "credit_expiry_days": (30, 1095),
}
SIBLING_BOUNDS: Final[Mapping[str, tuple[int, int]]] = {"percent_bps": (1, 10_000)}


class FamilyOffersStore(Protocol):
    async def get(self) -> Any: ...

    async def set_family_offers(
        self,
        *,
        referral_program: ReferralProgram | None = None,
        sibling_discount: SiblingDiscount | None = None,
    ) -> None: ...


class FamilyOffersView(BaseModel):
    model_config = {"frozen": True}

    referral_program: ReferralProgram
    sibling_discount: SiblingDiscount


class UpdateFamilyOffersCommand(BaseModel):
    """Each block is a partial patch: only the keys present are changed, and an
    explicit ``None`` clears a value. ``effective_from`` is never accepted."""

    model_config = {"frozen": True}

    referral_program: dict[str, Any] | None = None
    sibling_discount: dict[str, Any] | None = None
    actor_id: str
    reason: str | None = None


class GetFamilyOffers:
    def __init__(self, *, store: FamilyOffersStore) -> None:
        self._store = store

    async def execute(self) -> FamilyOffersView:
        settings = await self._store.get()
        return FamilyOffersView(
            referral_program=settings.referral_program,
            sibling_discount=settings.sibling_discount,
        )


class UpdateFamilyOffers:
    """Validate both blocks, write the changed ones, then audit each change."""

    def __init__(
        self,
        *,
        store: FamilyOffersStore,
        audit: RecordMoneySettingChange,
    ) -> None:
        self._store = store
        self._audit = audit

    async def execute(self, academy_id: str, cmd: UpdateFamilyOffersCommand) -> FamilyOffersView:
        current = await self._store.get()
        before_referral: ReferralProgram = current.referral_program
        before_sibling: SiblingDiscount = current.sibling_discount
        referral = before_referral
        sibling = before_sibling
        if cmd.referral_program is not None:
            referral = _merge(
                ReferralProgram, "referral_program", before_referral, cmd.referral_program
            )
            _check_bounds("referral_program", referral, REFERRAL_BOUNDS)
            if referral.enabled:
                # The values are stored now; the programme itself is C2. C2 adds
                # the switch-on rules and the effective_from stamp.
                raise BillingRulesValidationError(
                    "referral_program.enabled", "the referral programme is not available yet"
                )
        if cmd.sibling_discount is not None:
            sibling = _merge(
                SiblingDiscount, "sibling_discount", before_sibling, cmd.sibling_discount
            )
            _check_bounds("sibling_discount", sibling, SIBLING_BOUNDS)

        changed_referral = referral != before_referral
        changed_sibling = sibling != before_sibling
        if changed_referral or changed_sibling:
            await self._store.set_family_offers(
                referral_program=referral if changed_referral else None,
                sibling_discount=sibling if changed_sibling else None,
            )
        await self._record(academy_id, "referral_program_changed", before_referral, referral, cmd)
        await self._record(academy_id, "sibling_discount_changed", before_sibling, sibling, cmd)
        return FamilyOffersView(referral_program=referral, sibling_discount=sibling)

    async def _record(
        self,
        academy_id: str,
        action: MoneySettingAction,
        before: BaseModel,
        after: BaseModel,
        cmd: UpdateFamilyOffersCommand,
    ) -> None:
        # Best effort, like every money-setting audit: the write has landed.
        await self._audit.execute(
            academy_id=academy_id,
            action=action,
            actor_id=cmd.actor_id,
            before=before.model_dump(mode="json"),
            after=after.model_dump(mode="json"),
            reason=cmd.reason,
        )


def _merge[M: BaseModel](model: type[M], block: str, current: M, patch: dict[str, Any]) -> M:
    unknown = set(patch) - (set(model.model_fields) - {"effective_from"})
    if unknown:
        field = sorted(unknown)[0]
        raise BillingRulesValidationError(f"{block}.{field}", f"{field} cannot be set")
    values = {**current.model_dump(), **patch}
    if block == "sibling_discount" and values.get("enabled"):
        # Checked here too so the 422 names the field; the model validator
        # backstops stored data but cannot say which field is missing.
        for field in SIBLING_REQUIRED_ON_ENABLE:
            if values.get(field) is None:
                raise BillingRulesValidationError(
                    f"{block}.{field}", f"{field} is required to switch this offer on"
                )
    try:
        return model.model_validate(values)
    except ValidationError as exc:
        error = exc.errors()[0]
        field = ".".join(str(part) for part in error["loc"]) or "value"
        raise BillingRulesValidationError(f"{block}.{field}", error["msg"]) from exc


def _check_bounds(block: str, value: BaseModel, bounds: Mapping[str, tuple[int, int]]) -> None:
    for field, (low, high) in bounds.items():
        number = getattr(value, field)
        if number is not None and not low <= number <= high:
            raise BillingRulesValidationError(
                f"{block}.{field}", f"{field} must be between {low} and {high}"
            )
