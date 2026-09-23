/**
 * Pure view helpers for the People report cards on /admin/reports (roadmap L5a).
 *
 * Data in, plain values out: no DOM, no React and no runtime imports, so the
 * rows can be tested under plain `node --test`. The page formats money with
 * the one `formatCents` in `lib/money.ts`.
 *
 * Both normalizers accept anything: an e2e catch-all stub answers `{}`, and a
 * partial payload must render as "no data", never crash the Reports page.
 */

import type {
  AdminInquiryConversionResponse,
  AdminInquirySourceRow,
  AdminMoneyAgeBand,
  AdminMoneyOwedByAgeResponse,
} from "./api/admin";

export interface AgeRow {
  key: string;
  label: string;
  familyCount: number;
  totalCents: number;
}

export interface MoneyOwedView {
  asOf: string;
  rows: AgeRow[];
  overdueCents: number;
  overdueFamilies: number;
  balanceCents: number;
  owingFamilies: number;
}

const AGE_LABELS: Record<string, string> = {
  not_yet_due: "Not yet due",
  days_1_30: "1 to 30 days late",
  days_31_60: "31 to 60 days late",
  days_over_60: "Over 60 days late",
};

function count(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function ageRow(band: Partial<AdminMoneyAgeBand> | null | undefined): AgeRow | null {
  if (!band || typeof band.key !== "string") return null;
  return {
    key: band.key,
    label: AGE_LABELS[band.key] ?? (typeof band.label === "string" ? band.label : band.key),
    familyCount: count(band.family_count),
    totalCents: count(band.total_cents),
  };
}

/** `null` when the payload is not a money-owed report at all. */
export function normalizeMoneyOwed(raw: unknown): MoneyOwedView | null {
  const data = raw as Partial<AdminMoneyOwedByAgeResponse> | null | undefined;
  if (!data || !Array.isArray(data.bands) || typeof data.as_of !== "string") return null;
  const rows = [ageRow(data.not_yet_due), ...data.bands.map(ageRow)].filter(
    (row): row is AgeRow => row !== null,
  );
  return {
    asOf: data.as_of,
    rows,
    overdueCents: count(data.overdue_cents),
    overdueFamilies: count(data.overdue_family_count),
    balanceCents: count(data.balance_cents),
    owingFamilies: count(data.owing_family_count),
  };
}

export function familiesText(n: number): string {
  return `${n} ${n === 1 ? "family" : "families"}`;
}

/** 403 from the money route means "this role may not see money": hide the card. */
export function isMoneyHidden(error: unknown): boolean {
  return (error as { status?: number } | null)?.status === 403;
}

// ---------------------------------------------------------------- inquiries

const SOURCE_LABELS: Record<string, string> = {
  website: "Website form",
  whatsapp_or_phone: "WhatsApp or phone",
  referral: "Referral",
  other: "Other",
  all: "All sources",
};

export interface SourceRow {
  source: string;
  label: string;
  inquiries: number;
  lead: number;
  trial: number;
  enrolled: number;
  conversion: string;
}

export interface InquiryView {
  dateFrom: string;
  dateTo: string;
  timezone: string;
  rows: SourceRow[];
  total: SourceRow;
}

export function conversionText(rate: number | null | undefined): string {
  if (typeof rate !== "number" || !Number.isFinite(rate)) return "—";
  return `${Math.round(rate * 100)}%`;
}

function sourceRow(row: Partial<AdminInquirySourceRow> | null | undefined): SourceRow | null {
  if (!row || typeof row.source !== "string") return null;
  return {
    source: row.source,
    label: SOURCE_LABELS[row.source] ?? row.source,
    inquiries: count(row.inquiries),
    lead: count(row.lead),
    trial: count(row.trial),
    enrolled: count(row.enrolled),
    conversion: conversionText(row.conversion_rate),
  };
}

export function normalizeInquiry(raw: unknown): InquiryView | null {
  const data = raw as Partial<AdminInquiryConversionResponse> | null | undefined;
  if (!data || !Array.isArray(data.sources)) return null;
  const total = sourceRow(data.total);
  if (!total) return null;
  return {
    dateFrom: typeof data.date_from === "string" ? data.date_from : "",
    dateTo: typeof data.date_to === "string" ? data.date_to : "",
    timezone: typeof data.timezone === "string" ? data.timezone : "",
    rows: data.sources.map(sourceRow).filter((row): row is SourceRow => row !== null),
    total,
  };
}
