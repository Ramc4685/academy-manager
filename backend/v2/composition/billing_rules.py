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
    BuildBillingRulesView,
    CancellationPolicyLike,
    InvoiceScheduleReader,
    InvoiceScheduleWriter,
    UpdateBillingRules,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_audit_log import (
    MongoBillingAuditLogRepository,
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
    """Write the two cancellation fields, carrying the other four through.

    The Self-service panel owns the wider policy; Billing rules owns the two
    cancellation numbers. Both write the same stored document through
    ``UpdateSelfServicePolicy``, so there is one value, not two.
    """

    def __init__(self, *, reader: Any, writer: Any) -> None:
        self._reader = reader
        self._writer = writer

    async def execute(
        self,
        *,
        cancellation_minimum_notice_days: int,
        cancellation_fee_cents: int,
    ) -> CancellationPolicyLike:
        current = await self._reader.execute()
        updated = await self._writer.execute(
            UpdateSelfServicePolicyCommand(
                absence_notice_min_hours=current.absence_notice_min_hours,
                makeup_expiry_days=current.makeup_expiry_days,
                makeup_requires_notice=current.makeup_requires_notice,
                cancellation_minimum_notice_days=cancellation_minimum_notice_days,
                cancellation_fee_cents=cancellation_fee_cents,
                cancellation_effective_timing=current.cancellation_effective_timing,
            )
        )
        return cast(CancellationPolicyLike, updated)


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
    return AdminBillingRules(
        read=BuildBillingRulesView(
            schedule=schedule_reader,
            fees=admin.get_academy_fees_use_case,
            cancellation=policy_reader,
        ),
        write=UpdateBillingRules(
            schedule_reader=schedule_reader,
            schedule_writer=schedule_writer,
            fees_reader=admin.get_academy_fees_use_case,
            fees_writer=admin.update_academy_fees_use_case,
            cancellation_reader=policy_reader,
            cancellation_writer=policy_writer,
            audit=MongoBillingAuditLogRepository(db),
        ),
    )
