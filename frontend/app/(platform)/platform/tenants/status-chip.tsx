"use client";

import { Chip, type ChipVariant } from "@/components/ds";
import type { TenantStatus } from "@/lib/api/platform";

/** Tenant lifecycle statuses onto the closest existing DS chip families. */
const STATUS_VARIANT: Record<TenantStatus, ChipVariant> = {
  provisioning: "pending",
  active: "enrolled",
  suspended: "paused",
  cancelled: "expired",
};

const STATUS_LABEL: Record<TenantStatus, string> = {
  provisioning: "PROVISIONING",
  active: "ACTIVE",
  suspended: "SUSPENDED",
  cancelled: "CANCELLED",
};

export function TenantStatusChip({ status }: { status: TenantStatus }) {
  return <Chip variant={STATUS_VARIANT[status]} label={STATUS_LABEL[status]} />;
}
