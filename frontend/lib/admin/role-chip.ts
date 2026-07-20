import type { ChipVariant } from "@/components/ds/chip";

export function roleToChipVariant(role: string): ChipVariant {
  if (role === "admin") return "enrolled";
  if (role === "coach") return "autopayOn";
  return "manual";
}
