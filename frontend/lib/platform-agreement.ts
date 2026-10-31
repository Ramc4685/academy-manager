/**
 * Platform agreement and fee model display (roadmap L9c).
 *
 * The tenant record carries the fee model and who accepted which platform
 * agreement version, and when. A tenant in provisioning cannot be activated
 * until an acceptance is recorded; the API refuses with 409
 * Platform.TenantAgreementNotAccepted.
 */

import type { PlatformTenant, TenantFeeModel } from "./api/platform";

const FEE_MODEL_LABELS: Record<TenantFeeModel, string> = {
  flat_monthly: "Flat monthly fee",
};

/** Human label for a fee model; unknown codes are shown as-is. */
export function formatFeeModel(model: string): string {
  return FEE_MODEL_LABELS[model as TenantFeeModel] ?? model;
}

type AgreementFields = Pick<
  PlatformTenant,
  | "platform_agreement_version"
  | "platform_agreement_accepted_at"
  | "platform_agreement_accepted_by"
>;

/** True only when version, time and signatory are all on record. */
export function hasAcceptedAgreement(tenant: AgreementFields): boolean {
  return Boolean(
    tenant.platform_agreement_version?.trim() &&
      tenant.platform_agreement_accepted_at &&
      tenant.platform_agreement_accepted_by?.trim(),
  );
}

/** "12 Oct 2026" style date for an acceptance timestamp; "—" when missing. */
export function formatAcceptedAt(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

/**
 * Warning shown before a new acceptance replaces the one on record, or null
 * when nothing is recorded yet. The tenant record keeps only the latest
 * acceptance; the replaced one survives in the platform audit log
 * (tenant.agreement_accepted, "before" snapshot).
 */
export function replacedAcceptanceWarning(tenant: AgreementFields): string | null {
  if (!hasAcceptedAgreement(tenant)) return null;
  return (
    `This replaces the acceptance on record: version ${tenant.platform_agreement_version} ` +
    `by ${tenant.platform_agreement_accepted_by} on ` +
    `${formatAcceptedAt(tenant.platform_agreement_accepted_at)}. ` +
    "The replaced record is kept only in the platform audit log."
  );
}
