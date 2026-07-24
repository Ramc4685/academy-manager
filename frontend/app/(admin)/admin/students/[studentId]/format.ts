import type { TuitionDiscountKind } from "@/lib/api/v2/students";

function formatCurrencyCents(cents: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(cents / 100);
}

function centsToDollarInput(cents: number) {
  return (cents / 100).toFixed(2);
}

function dollarsToCents(value: string) {
  const normalized = value.replace(/[$,]/g, "").trim();
  if (!normalized) return 0;
  const amount = Number.parseFloat(normalized);
  if (!Number.isFinite(amount)) return -1;
  return Math.round(amount * 100);
}

function getErrorMessage(error: unknown) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : "Request failed.";
  if (message.includes("no_saved_payment_method")) {
    return "This parent has no saved card on file. Use Send to email a payment link, or Record payment to log a manual payment.";
  }
  return message;
}

function formatDate(value: string | null | undefined) {
  if (!value) return "—";
  return new Date(value).toLocaleDateString();
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return "—";
  return new Date(value).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatDateTimeRange(
  startAt: string | null | undefined,
  endAt: string | null | undefined,
) {
  if (!startAt && !endAt) return "—";
  if (!endAt) return formatDateTime(startAt);
  if (!startAt) return formatDateTime(endAt);
  return `${formatDateTime(startAt)} - ${formatDateTime(endAt)}`;
}

function previewNetCents(
  grossCents: number,
  kind: TuitionDiscountKind,
  value: string,
): number {
  const v = Number(value) || 0;
  switch (kind) {
    case "waiver":
      return 0;
    case "percent":
      return Math.max(grossCents - Math.round((grossCents * v) / 100), 0);
    case "amount_off":
      return Math.max(grossCents - Math.round(v * 100), 0);
    case "fixed_net":
      return Math.max(Math.round(v * 100), 0);
    default:
      return grossCents;
  }
}

export {
  formatCurrencyCents,
  centsToDollarInput,
  dollarsToCents,
  getErrorMessage,
  formatDate,
  formatDateTime,
  formatDateTimeRange,
  previewNetCents,
};
