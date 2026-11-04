/**
 * Pure view helpers for the People report cards on /admin/reports (roadmap L5a
 * and L5b).
 *
 * Data in, plain values out: no DOM, no React and no runtime imports, so the
 * rows can be tested under plain `node --test`. The page formats money with
 * the one `formatCents` in `lib/money.ts`.
 *
 * Both normalizers accept anything: an e2e catch-all stub answers `{}`, and a
 * partial payload must render as "no data", never crash the Reports page.
 */

import type {
  AdminAttendanceRiskResponse,
  AdminFamiliesLostResponse,
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

// ---------------------------------------------------------------- attendance risk (L5b)

export interface RiskRow {
  key: string;
  label: string;
  /** The coach column on the by-class table; empty on the by-coach table. */
  coach: string;
  classes: number;
  students: number;
  atRisk: number;
  share: string;
}

export interface AttendanceRiskView {
  byClass: RiskRow[];
  byCoach: RiskRow[];
  students: number;
  atRisk: number;
}

const NO_COACH = "No coach assigned";

function list(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((row): row is Record<string, unknown> => !!row && typeof row === "object")
    : [];
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

/** `null` when the payload is not an attendance risk report. */
export function normalizeAttendanceRisk(raw: unknown): AttendanceRiskView | null {
  const data = raw as Partial<AdminAttendanceRiskResponse> | null | undefined;
  if (!data || !Array.isArray(data.by_class) || !Array.isArray(data.by_coach)) return null;
  const byClass = list(data.by_class).map((row, i): RiskRow => {
    const id = text(row.session_id) ?? `class-${i}`;
    return {
      key: id,
      label: text(row.title) ?? id,
      coach: text(row.coach_name) ?? (text(row.coach_id) ? "Unnamed coach" : NO_COACH),
      classes: 1,
      students: count(row.students),
      atRisk: count(row.at_risk),
      share: conversionText(row.at_risk_rate as number | null | undefined),
    };
  });
  const byCoach = list(data.by_coach).map((row, i): RiskRow => {
    const id = text(row.coach_id);
    return {
      key: id ?? `no-coach-${i}`,
      label: text(row.coach_name) ?? (id ? "Unnamed coach" : NO_COACH),
      coach: "",
      classes: count(row.classes),
      students: count(row.students),
      atRisk: count(row.at_risk),
      share: conversionText(row.at_risk_rate as number | null | undefined),
    };
  });
  return { byClass, byCoach, students: count(data.students), atRisk: count(data.at_risk) };
}

export function studentsText(n: number): string {
  return `${n} ${n === 1 ? "student" : "students"}`;
}

// ---------------------------------------------------------------- families lost (L5b)

export interface ReasonRow {
  key: string;
  /** Server label, when it sent one (transitions); reasons are labelled by the page. */
  label: string | null;
  families: number;
}

export interface FamiliesLostView {
  dateFrom: string;
  dateTo: string;
  timezone: string;
  familiesLost: number;
  /** Only reasons with at least one family, most families first. */
  reasons: ReasonRow[];
  withReason: number;
  transitions: ReasonRow[];
  withoutReason: number;
}

function reasonRows(value: unknown): ReasonRow[] {
  return list(value)
    .map((row) => ({
      key: text(row.key) ?? "",
      label: text(row.label),
      families: count(row.families),
    }))
    .filter((row) => row.key !== "" && row.families > 0)
    .sort((a, b) => b.families - a.families);
}

export function normalizeFamiliesLost(raw: unknown): FamiliesLostView | null {
  const data = raw as Partial<AdminFamiliesLostResponse> | null | undefined;
  if (!data || !Array.isArray(data.by_reason) || !Array.isArray(data.by_transition)) return null;
  return {
    dateFrom: typeof data.date_from === "string" ? data.date_from : "",
    dateTo: typeof data.date_to === "string" ? data.date_to : "",
    timezone: typeof data.timezone === "string" ? data.timezone : "",
    familiesLost: count(data.families_lost),
    reasons: reasonRows(data.by_reason),
    withReason: count(data.with_reason),
    transitions: reasonRows(data.by_transition),
    withoutReason: count(data.without_reason),
  };
}
