"""Composition for Settings -> Billing rules (``/admin/billing/rules``).

Lives outside ``composition/admin.py`` because that module sits at its wiring
line budget. Pure wiring: it reuses the use cases already built on
``AdminUseCases`` and adapts the two that belong to other bounded contexts
(academy fees in identity, the parent self-service policy in enrollment) onto
the narrow ports the billing-rules use cases declare.

Nothing tenant-specific is captured here — the fees use cases take
``academy_id`` per request, and the billing-settings/self-service repositories
resolve the tenant at execution time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from backend.v2.contexts.billing.application.use_cases.billing_rules import (
    AchDiscountLike,
    BuildBillingRulesView,
    CancellationPolicyLike,
    DropDefaultOutcomeLike,
    InvoiceScheduleReader,
    InvoiceScheduleWriter,
    UpdateBillingRules,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_audit_log import (
    MongoBillingAuditLogRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)
from backend.v2.contexts.enrollment.application.use_cases.departure_policies import (
    UpdateEnrollmentDeparturePolicyCommand,
)
from backend.v2.contexts.enrollment.application.use_cases.self_service_policies import (
    UpdateSelfServicePolicyCommand,
)
from backend.v2.interfaces.admin.deps import AdminUseCases


@dataclass(frozen=True)
class AdminBillingRules:
    """What ``interfaces/admin/billing_rules_routes.py`` reads off app.state."""

    read: BuildBillingRulesView
    write: UpdateBillingRules


class _CancellationPolicyAdapter:
    """Write the two cancellation fields and nothing else.

    The Self-service panel owns the wider policy; Billing rules owns the two
    cancellation numbers. Both write the same stored document through
    ``UpdateSelfServicePolicy``, so there is one value, not two. The write is
    partial: re-sending the other four fields from a read taken moments
    earlier could put back a value another admin had just saved (money audit
    X5). ``PUT /admin/self-service/policy`` also routes its cancellation
    changes through ``UpdateBillingRules``, and so through this adapter.
    """

    def __init__(self, *, reader: Any, writer: Any) -> None:
        self._reader = reader
        self._writer = writer

    async def execute(
        self,
        *,
        cancellation_minimum_notice_days: int | None = None,
        cancellation_fee_cents: int | None = None,
        cancellation_effective_timing: str | None = None,
    ) -> CancellationPolicyLike:
        updated = await self._writer.execute(
            UpdateSelfServicePolicyCommand(
                cancellation_minimum_notice_days=cancellation_minimum_notice_days,
                cancellation_fee_cents=cancellation_fee_cents,
                cancellation_effective_timing=cancellation_effective_timing,
            )
        )
        return cast(CancellationPolicyLike, updated)


class _DropDefaultOutcomeAdapter:
    """Write ``drop_default_outcome`` and nothing else.

    The Holds card owns the other three fields of ``EnrollmentDeparturePolicy``
    (``max_hold_days``, ``hold_reclaim_policy``,
    ``delete_enrollment_requires_owner``); Billing rules owns this one. The
    underlying command treats every field as optional and leaves an omitted
    one untouched (``UpdateEnrollmentDeparturePolicy``), so this write cannot
    put back a stale Holds value.
    """

    def __init__(self, *, reader: Any, writer: Any) -> None:
        self._reader = reader
        self._writer = writer

    async def execute(self, *, drop_default_outcome: str | None = None) -> DropDefaultOutcomeLike:
        updated = await self._writer.execute(
            UpdateEnrollmentDeparturePolicyCommand(drop_default_outcome=drop_default_outcome)
        )
        return cast(DropDefaultOutcomeLike, updated)


class _AchDiscountAdapter:
    """Read and write the ACH discount on ``billing_settings``.

    Read-modify-write through the settings repository, which never persists
    ``max_ach_discount_percent`` (the platform-owned ceiling), so this write
    cannot raise it. Only ``ach_discount_enabled`` and ``ach_discount_percent``
    are changed.
    """

    def __init__(self, settings: MongoBillingSettingsRepository) -> None:
        self._settings = settings

    async def read(self) -> AchDiscountLike:
        return await self._settings.get()

    async def write(self, *, enabled: bool, percent: float) -> AchDiscountLike:
        current = await self._settings.get()
        updated = current.model_copy(
            update={"ach_discount_enabled": enabled, "ach_discount_percent": percent}
        )
        await self._settings.upsert(updated)
        return updated


class _Call:
    def __init__(self, fn: Any) -> None:
        self.execute = fn


def _required(value: Any, name: str) -> Any:
    if value is None:
        raise RuntimeError(f"billing rules needs {name} wired on AdminUseCases")
    return value


def compose_admin_billing_rules(db: Any, admin: AdminUseCases) -> AdminBillingRules:
    schedule_reader = cast(
        InvoiceScheduleReader, _required(admin.get_invoice_schedule, "get_invoice_schedule")
    )
    schedule_writer = cast(
        InvoiceScheduleWriter, _required(admin.set_invoice_schedule, "set_invoice_schedule")
    )
    policy_reader = _required(admin.self_service_policy, "self_service_policy")
    policy_writer = _CancellationPolicyAdapter(
        reader=policy_reader,
        writer=_required(admin.update_self_service_policy, "update_self_service_policy"),
    )
    drop_outcome_reader = _required(admin.departure_policy, "departure_policy")
    drop_outcome_writer = _DropDefaultOutcomeAdapter(
        reader=drop_outcome_reader,
        writer=_required(admin.update_departure_policy, "update_departure_policy"),
    )
    ach = _AchDiscountAdapter(MongoBillingSettingsRepository(db))
    return AdminBillingRules(
        read=BuildBillingRulesView(
            schedule=schedule_reader,
            fees=admin.get_academy_fees_use_case,
            cancellation=policy_reader,
            drop_outcome=drop_outcome_reader,
            ach=_Call(ach.read),
        ),
        write=UpdateBillingRules(
            schedule_reader=schedule_reader,
            schedule_writer=schedule_writer,
            fees_reader=admin.get_academy_fees_use_case,
            fees_writer=admin.update_academy_fees_use_case,
            cancellation_reader=policy_reader,
            cancellation_writer=policy_writer,
            drop_outcome_reader=drop_outcome_reader,
            drop_outcome_writer=drop_outcome_writer,
            ach_reader=_Call(ach.read),
            ach_writer=_Call(ach.write),
            audit=MongoBillingAuditLogRepository(db),
        ),
    )
