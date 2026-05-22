"""Platform tenant lifecycle domain models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

TenantStatus = Literal["provisioning", "active", "suspended", "cancelled"]


class TenantLimits(BaseModel, frozen=True):
    """Plan limits owned by the Platform context."""

    max_students: int | None = Field(default=None, ge=0)
    max_coaches: int | None = Field(default=None, ge=0)
    max_locations: int | None = Field(default=None, ge=0)


class TenantHealth(BaseModel, frozen=True):
    """Tenant serving health used before allowing tenant-scoped requests."""

    academy_id: str
    status: TenantStatus
    servable: bool
    reason: str | None = None
    plan_code: str
    limits: TenantLimits


class Tenant(BaseModel, frozen=True):
    """Platform-owned tenant aggregate.

    `academy_id` remains the tenant identifier used by v2 tenant-scoped data.
    The platform context owns the status and plan/limits lifecycle for that
    tenant. Business contexts must not mutate these fields directly.
    """

    academy_id: str
    display_name: str
    slug: str
    primary_domain: str
    status: TenantStatus = "provisioning"
    plan_code: str
    limits: TenantLimits = Field(default_factory=TenantLimits)
    status_reason: str | None = None
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime
    activated_at: datetime | None = None
    suspended_at: datetime | None = None
    cancelled_at: datetime | None = None
    reactivated_at: datetime | None = None

    @field_validator(
        "display_name", "slug", "primary_domain", "plan_code", "created_by", "updated_by"
    )
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field is required")
        return stripped

    def is_servable(self) -> bool:
        return self.status == "active"

    def health(self) -> TenantHealth:
        if self.is_servable():
            reason = None
        else:
            reason = f"tenant_status_{self.status}"
        return TenantHealth(
            academy_id=self.academy_id,
            status=self.status,
            servable=self.is_servable(),
            reason=reason,
            plan_code=self.plan_code,
            limits=self.limits,
        )
