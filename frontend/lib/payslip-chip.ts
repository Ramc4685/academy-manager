import type { ChipVariant } from "@/components/ds/chip";
import type { MonthlyPayrollStatus } from "./api/v2/payroll";

export interface PayslipChipSpec {
  variant: ChipVariant;
  label: string;
}

/**
 * Maps a coach's current-month payroll status (and paid_at, which still wins once
 * set) to the Chip variant/label the Payslips overview should show.
 *
 * Before this, PayslipsPanel derived status from `paid_at` alone, so an approved
 * payslip that hadn't been paid yet was mislabelled DRAFT (#845).
 */
export function payslipChipFor(
  status: MonthlyPayrollStatus | undefined,
  paidAt: string | null | undefined,
): PayslipChipSpec {
  if (paidAt || status === "paid") {
    return { variant: "paid", label: "PAID" };
  }
  if (status === "approved") {
    return { variant: "approved", label: "APPROVED" };
  }
  if (status === "not_generated") {
    return { variant: "draft", label: "NOT GENERATED" };
  }
  return { variant: "draft", label: "DRAFT" };
}
