import type { ChipVariant } from "@/components/ds/chip";

export function roleToChipVariant(role: string): ChipVariant {
  if (role === "admin") return "enrolled";
  if (role === "coach") return "autopayOn";
  // Same blue family as coach, lighter dot: an assistant is coaching staff
  // without a payroll row or a lead surface.
  if (role === "assistant_coach") return "makeup";
  return "manual";
}
