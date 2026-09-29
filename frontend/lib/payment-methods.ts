/**
 * Offline (manual) payment methods: the one frontend list (row 22).
 *
 * Same six, same order as the backend (`identity/domain/manual_payment_methods.py`
 * and billing's `ManualPaymentMethod`). The academy's owner chooses which of
 * them the incoming-payment dialogs offer (Settings → Billing rules → Offline
 * payments); until they do, every academy offers all six with cash first,
 * which is what the dialogs always hardcoded.
 */

export const MANUAL_PAYMENT_METHODS = [
  "cash",
  "check",
  "zelle",
  "venmo",
  "bank_transfer",
  "other",
] as const;

export type ManualPaymentMethod = (typeof MANUAL_PAYMENT_METHODS)[number];

export const MANUAL_PAYMENT_METHOD_LABELS: Record<ManualPaymentMethod, string> = {
  cash: "Cash",
  check: "Check",
  zelle: "Zelle",
  venmo: "Venmo",
  bank_transfer: "Bank transfer",
  other: "Other",
};

export interface ManualMethodOption {
  value: ManualPaymentMethod;
  label: string;
}

export function isManualPaymentMethod(value: unknown): value is ManualPaymentMethod {
  return (MANUAL_PAYMENT_METHODS as readonly unknown[]).includes(value);
}

/**
 * The dialog options for an academy's enabled list, in canonical order.
 * Unknown values are dropped; a missing or empty list means all six, so a
 * slow or failed read never leaves a dialog with nothing to pick.
 */
export function manualMethodOptions(enabled: readonly string[] | null | undefined): ManualMethodOption[] {
  const chosen = MANUAL_PAYMENT_METHODS.filter((method) => enabled?.includes(method));
  const methods = chosen.length > 0 ? chosen : MANUAL_PAYMENT_METHODS;
  return methods.map((value) => ({ value, label: MANUAL_PAYMENT_METHOD_LABELS[value] }));
}

/** The picked method if still offered, else the first offered one (the default). */
export function resolveManualMethod(
  picked: string | null,
  options: readonly ManualMethodOption[],
): ManualPaymentMethod {
  const match = options.find((option) => option.value === picked);
  return (match ?? options[0] ?? { value: "cash" as const }).value;
}
