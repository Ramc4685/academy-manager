"""Per-academy platform application fee (roadmap L9b): pure rules + use cases."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.v2.contexts.billing.application.use_cases.application_fee import (
    GetApplicationFee,
    SetApplicationFee,
    SetApplicationFeeCommand,
    application_fee_kwargs,
    idempotency_key_with_fee,
    resolve_application_fee_cents,
)
from backend.v2.contexts.billing.domain.billing_audit import BillingAuditEntry
from backend.v2.contexts.billing.domain.billing_settings import (
    MAX_APPLICATION_FEE_BPS,
    BillingSettings,
)
from backend.v2.contexts.billing.domain.errors import ApplicationFeeAcademyNotFound
from backend.v2.contexts.billing.domain.fees import (
    application_fee_cents,
    check_application_fee_cents,
)
from backend.v2.shared.tenancy import current_academy_id

# ---------------------------------------------------------------------------
# Domain: fee math and validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("amount", "bps", "expected"),
    [
        (15_000, 0, 0),  # default: no fee, behaviour unchanged
        (0, 250, 0),
        (15_000, 250, 375),  # 2.5% of $150.00
        (4_100, 250, 102),  # 102.5 -> floor: the half cent stays with the academy
        (1, 999, 0),  # sub-cent fee rounds to nothing
        (10_001, 1_000, 1_000),  # 10% cap, floored
        (100, 10_000, 100),  # 100% is exactly the charge, never more
    ],
)
def test_application_fee_cents_floors_and_never_exceeds_the_charge(
    amount: int, bps: int, expected: int
) -> None:
    assert application_fee_cents(amount, bps) == expected
    assert application_fee_cents(amount, bps) <= amount


def test_application_fee_cents_rejects_negative_inputs() -> None:
    with pytest.raises(ValueError):
        application_fee_cents(-1, 100)
    with pytest.raises(ValueError):
        application_fee_cents(100, -1)


def test_check_application_fee_cents_accepts_zero_with_or_without_account() -> None:
    assert (
        check_application_fee_cents(fee_cents=0, amount_cents=100, connected_account_id=None) == 0
    )
    assert (
        check_application_fee_cents(fee_cents=100, amount_cents=100, connected_account_id="acct_1")
        == 100
    )


@pytest.mark.parametrize(
    ("fee", "amount", "account"),
    [
        (101, 100, "acct_1"),  # more than the charge
        (-1, 100, "acct_1"),  # negative
        (5, 100, None),  # fee on a platform-direct charge
        (1.5, 100, "acct_1"),  # not integer cents
        (True, 100, "acct_1"),  # bool is not a cent amount
    ],
)
def test_check_application_fee_cents_rejects_invalid_fees(
    fee: object, amount: int, account: str | None
) -> None:
    with pytest.raises(ValueError):
        check_application_fee_cents(
            fee_cents=fee,  # type: ignore[arg-type]
            amount_cents=amount,
            connected_account_id=account,
        )


def test_billing_settings_default_fee_is_zero_and_bounded() -> None:
    assert BillingSettings.default("acad-1").application_fee_bps == 0
    BillingSettings(academy_id="acad-1", application_fee_bps=MAX_APPLICATION_FEE_BPS)
    with pytest.raises(ValidationError):
        BillingSettings(academy_id="acad-1", application_fee_bps=MAX_APPLICATION_FEE_BPS + 1)
    with pytest.raises(ValidationError):
        BillingSettings(academy_id="acad-1", application_fee_bps=-1)


# ---------------------------------------------------------------------------
# Charge-time helpers
# ---------------------------------------------------------------------------


class _Settings:
    """In-memory BillingSettingsRepository keyed by the current tenant.

    Mirrors the Mongo repo's split: ``upsert`` never writes the fee, only
    ``set_application_fee_bps`` does.
    """

    def __init__(self, fees: dict[str, int] | None = None, *, fail: bool = False) -> None:
        self.fees = dict(fees or {})
        self.fail = fail
        self.fee_writes: list[tuple[str, int]] = []

    async def get(self) -> BillingSettings:
        if self.fail:
            raise RuntimeError("settings store down")
        academy_id = current_academy_id()
        return BillingSettings(
            academy_id=academy_id, application_fee_bps=self.fees.get(academy_id, 0)
        )

    async def upsert(self, settings: BillingSettings) -> None:  # pragma: no cover - unused
        return None

    async def set_application_fee_bps(self, fee_bps: int) -> None:
        academy_id = current_academy_id()
        self.fees[academy_id] = fee_bps
        self.fee_writes.append((academy_id, fee_bps))


async def test_resolve_fee_is_zero_without_a_connected_account() -> None:
    from backend.v2.shared.tenancy import tenant_scope

    with tenant_scope("acad-1"):
        fee = await resolve_application_fee_cents(
            _Settings({"acad-1": 500}), amount_cents=10_000, connected_account_id=None
        )
    assert fee == 0


async def test_resolve_fee_uses_the_current_academys_bps() -> None:
    from backend.v2.shared.tenancy import tenant_scope

    settings = _Settings({"acad-1": 250, "acad-2": 0})
    with tenant_scope("acad-1"):
        assert (
            await resolve_application_fee_cents(
                settings, amount_cents=15_000, connected_account_id="acct_1"
            )
            == 375
        )
    with tenant_scope("acad-2"):
        assert (
            await resolve_application_fee_cents(
                settings, amount_cents=15_000, connected_account_id="acct_2"
            )
            == 0
        )


async def test_resolve_fee_falls_back_to_zero_when_settings_fail() -> None:
    from backend.v2.shared.tenancy import tenant_scope

    with tenant_scope("acad-1"):
        fee = await resolve_application_fee_cents(
            _Settings(fail=True), amount_cents=15_000, connected_account_id="acct_1"
        )
    assert fee == 0


def test_zero_fee_keeps_gateway_call_and_idempotency_key_unchanged() -> None:
    assert application_fee_kwargs(0) == {}
    assert idempotency_key_with_fee("autopay:inv-1:2026-09:4100", 0) == "autopay:inv-1:2026-09:4100"
    assert application_fee_kwargs(102) == {"application_fee_cents": 102}
    assert (
        idempotency_key_with_fee("autopay:inv-1:2026-09:4100", 102)
        == "autopay:inv-1:2026-09:4100:fee102"
    )


# ---------------------------------------------------------------------------
# Platform-admin use cases
# ---------------------------------------------------------------------------


class _Audit:
    def __init__(self) -> None:
        self.entries: list[BillingAuditEntry] = []

    async def append(self, entry: BillingAuditEntry) -> None:
        self.entries.append(entry)


async def _exists(academy_id: str) -> bool:
    return academy_id in {"acad-1", "acad-2"}


async def test_set_application_fee_writes_only_the_named_academy_and_audits() -> None:
    settings = _Settings()
    audit = _Audit()
    use_case = SetApplicationFee(
        settings=settings,
        audit=audit,
        academy_exists=_exists,
        clock=lambda: datetime(2026, 9, 24, tzinfo=UTC),
    )

    result = await use_case.execute(
        SetApplicationFeeCommand(
            academy_id="acad-1", application_fee_bps=250, actor_id="platform-admin"
        )
    )

    assert result.application_fee_bps == 250
    assert settings.fee_writes == [("acad-1", 250)]
    assert len(audit.entries) == 1
    entry = audit.entries[0]
    assert entry.academy_id == "acad-1"
    assert entry.action == "application_fee_changed"
    assert entry.actor_id == "platform-admin"
    assert entry.before == {"application_fee_bps": 0}
    assert entry.after == {"application_fee_bps": 250}


async def test_set_application_fee_same_value_is_a_no_op() -> None:
    settings = _Settings({"acad-1": 250})
    audit = _Audit()
    use_case = SetApplicationFee(settings=settings, audit=audit, academy_exists=_exists)

    await use_case.execute(
        SetApplicationFeeCommand(academy_id="acad-1", application_fee_bps=250, actor_id="p")
    )

    assert settings.fee_writes == []
    assert audit.entries == []


async def test_set_and_get_application_fee_refuse_unknown_academy() -> None:
    settings = _Settings()
    with pytest.raises(ApplicationFeeAcademyNotFound):
        await SetApplicationFee(settings=settings, academy_exists=_exists).execute(
            SetApplicationFeeCommand(academy_id="acad-zz", application_fee_bps=100, actor_id="p")
        )
    with pytest.raises(ApplicationFeeAcademyNotFound):
        await GetApplicationFee(settings=settings, academy_exists=_exists).execute("acad-zz")
    assert settings.fee_writes == []


async def test_get_application_fee_reads_the_named_academy() -> None:
    use_case = GetApplicationFee(settings=_Settings({"acad-2": 125}), academy_exists=_exists)

    assert (await use_case.execute("acad-2")).application_fee_bps == 125
    assert (await use_case.execute("acad-1")).application_fee_bps == 0


def test_set_application_fee_command_is_bounded() -> None:
    with pytest.raises(ValidationError):
        SetApplicationFeeCommand(
            academy_id="acad-1", application_fee_bps=MAX_APPLICATION_FEE_BPS + 1, actor_id="p"
        )
    with pytest.raises(ValidationError):
        SetApplicationFeeCommand(academy_id="acad-1", application_fee_bps=-1, actor_id="p")
