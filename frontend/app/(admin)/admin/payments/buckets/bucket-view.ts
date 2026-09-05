/**
 * Pure view helpers for the Payments bucket list.
 *
 * Everything here is data-in / string-out so it can be unit tested without a
 * DOM. Bucket order, titles and actions come from the payments buckets spec
 * (docs/superpowers/specs/2026-09-05-payments-buckets-design.md §2, §4).
 */

import type { ChipVariant } from "@/components/ds/chip";
import type {
  AdminCollectionsBucket,
  AdminCollectionsFamily,
  AdminCollectionsView,
  CollectionsAction,
  CollectionsBucketKey,
} from "@/lib/api/admin";
import { formatCents, formatDateOnly } from "@/lib/money";
import { paymentMethodLabel } from "../format";

export const BUCKET_ORDER: CollectionsBucketKey[] = [
  "failed_autopay",
  "past_due",
  "awaiting",
  "autopay_scheduled",
  "paused",
  "paid",
];

export const BUCKET_META: Record<
  CollectionsBucketKey,
  { title: string; hint: string; stripe: string; emptyLine: string }
> = {
  failed_autopay: {
    title: "Failed autopay",
    hint: "The card was charged and declined. Message the family or record a payment.",
    stripe: "bg-status-red-500",
    emptyLine: "No failed autopay",
  },
  past_due: {
    title: "Past due",
    hint: "Open invoices past their due date with no autopay to collect them.",
    stripe: "bg-status-amber-500",
    emptyLine: "No past due families",
  },
  awaiting: {
    title: "Awaiting payment",
    hint: "Invoices sent and not yet due. The family pays by card, Zelle or cash.",
    stripe: "bg-teal-500",
    emptyLine: "No families awaiting payment",
  },
  autopay_scheduled: {
    title: "Autopay scheduled",
    hint: "Autopay charges these cards on the due date at 9:00 AM. Nothing to do unless you skip a month.",
    stripe: "bg-status-green-500",
    emptyLine: "No autopay scheduled",
  },
  paused: {
    title: "Paused",
    hint: "Enrollment paused, not invoiced this month. Resume when the family is back.",
    stripe: "bg-slate-400",
    emptyLine: "No paused families",
  },
  paid: {
    title: "Paid",
    hint: "Settled this month.",
    stripe: "bg-slate-200",
    emptyLine: "No payments yet this month",
  },
};

export const ACTION_LABEL: Record<CollectionsAction, string> = {
  send_reminder: "Send reminder",
  record_payment: "Record payment",
  message: "Message",
  skip_month: "Skip this month",
  resume: "Resume",
};

const ZERO_TOTALS: AdminCollectionsView["totals"] = {
  owed_cents: 0,
  autopay_scheduled_cents: 0,
  autopay_scheduled_count: 0,
  needs_action_count: 0,
  collected_cents: 0,
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function numberOr(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function emptyBucket(key: CollectionsBucketKey): AdminCollectionsBucket {
  return { key, count: 0, total_cents: 0, families: [] };
}

/**
 * Coerce whatever the collections endpoint (or an e2e stub returning
 * `{ payments: [] }`) gave us into a full view: zero totals and six empty
 * buckets in BUCKET_ORDER when anything is missing. Never throws.
 */
export function normalizeCollections(data: unknown): AdminCollectionsView {
  const raw = isRecord(data) ? data : {};
  const rawTotals = isRecord(raw.totals) ? raw.totals : {};
  const totals: AdminCollectionsView["totals"] = {
    owed_cents: numberOr(rawTotals.owed_cents, 0),
    autopay_scheduled_cents: numberOr(rawTotals.autopay_scheduled_cents, 0),
    autopay_scheduled_count: numberOr(rawTotals.autopay_scheduled_count, 0),
    needs_action_count: numberOr(rawTotals.needs_action_count, 0),
    collected_cents: numberOr(rawTotals.collected_cents, 0),
  };
  const rawBuckets = Array.isArray(raw.buckets) ? raw.buckets : [];
  const byKey = new Map<CollectionsBucketKey, AdminCollectionsBucket>();
  for (const entry of rawBuckets) {
    if (!isRecord(entry) || typeof entry.key !== "string") continue;
    const key = entry.key as CollectionsBucketKey;
    if (!BUCKET_ORDER.includes(key)) continue;
    const families = Array.isArray(entry.families)
      ? (entry.families as AdminCollectionsFamily[])
      : [];
    byKey.set(key, {
      key,
      count: numberOr(entry.count, families.length),
      total_cents: numberOr(entry.total_cents, 0),
      families,
    });
  }
  return {
    period: typeof raw.period === "string" ? raw.period : "",
    generated_at: typeof raw.generated_at === "string" ? raw.generated_at : "",
    timezone: typeof raw.timezone === "string" ? raw.timezone : "",
    totals: { ...ZERO_TOTALS, ...totals },
    buckets: BUCKET_ORDER.map((key) => byKey.get(key) ?? emptyBucket(key)),
  };
}

function dateOnlyUTC(iso: string): number {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!match) return Number.NaN;
  return Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
}

/** Whole calendar days from `fromISO` to `toISO` (positive when `to` is later). */
export function daysBetween(fromISO: string, toISO: string): number {
  const from = dateOnlyUTC(fromISO);
  const to = dateOnlyUTC(toISO);
  if (Number.isNaN(from) || Number.isNaN(to)) return 0;
  return Math.round((to - from) / 86_400_000);
}

/** "Hannah · Wed 6:15 Intermediate, Arjun" */
export function studentLine(family: AdminCollectionsFamily): string {
  return family.students
    .map((s) => (s.session_title ? `${s.name} · ${s.session_title}` : s.name))
    .join(", ");
}

/** Display name for a family row. */
export function familyName(family: AdminCollectionsFamily): string {
  return family.parent_name || family.parent_email || "Family on file";
}

/** Invoices in the family that still carry a balance, earliest due first. */
export function owingInvoices(family: AdminCollectionsFamily): AdminCollectionsFamily["invoices"] {
  return family.invoices
    .filter((inv) => inv.balance_due_cents > 0)
    .sort((a, b) => (a.due_date < b.due_date ? -1 : a.due_date > b.due_date ? 1 : 0));
}

function primaryInvoice(family: AdminCollectionsFamily) {
  return owingInvoices(family)[0] ?? family.invoices[0] ?? null;
}

function pluralDays(n: number): string {
  return `${n} ${n === 1 ? "DAY" : "DAYS"}`;
}

const UNKNOWN_AUTOPAY = new Set(["card_state_unknown", "connected_account_unknown", "unknown"]);

export function familyChip(
  bucket: CollectionsBucketKey,
  family: AdminCollectionsFamily,
  today: string = todayISO(),
): { variant: ChipVariant; label: string } {
  switch (bucket) {
    case "failed_autopay":
      return { variant: "failed", label: family.failure?.disabled ? "DISABLED" : "FAILED" };
    case "past_due": {
      const inv = primaryInvoice(family);
      const late = inv ? Math.max(daysBetween(inv.due_date, today), 0) : 0;
      return { variant: "overdue", label: `${pluralDays(late)} LATE` };
    }
    case "awaiting": {
      const status = family.autopay?.status;
      if (status === "no_card_on_file") return { variant: "pending", label: "NO CARD ON FILE" };
      if (status && UNKNOWN_AUTOPAY.has(status)) {
        return { variant: "pending", label: "AUTOPAY STATUS UNAVAILABLE" };
      }
      const inv = primaryInvoice(family);
      const until = inv ? daysBetween(today, inv.due_date) : 0;
      if (until <= 0) return { variant: "pending", label: "DUE TODAY" };
      return { variant: "pending", label: `DUE IN ${pluralDays(until)}` };
    }
    case "autopay_scheduled":
      return { variant: "autopayOn", label: "AUTOPAY" };
    case "paused":
      return { variant: "paused", label: "PAUSED" };
    case "paid":
      return { variant: "paid", label: "PAID" };
  }
}

function humanize(value: string | null | undefined): string | null {
  if (!value) return null;
  return value.replaceAll("_", " ");
}

function titleCase(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1).toLowerCase();
}

function monthsOwed(family: AdminCollectionsFamily): number {
  const owing = owingInvoices(family).length;
  return owing + (family.leftover_balance_cents > 0 ? 1 : 0);
}

export function secondaryLine(
  bucket: CollectionsBucketKey,
  family: AdminCollectionsFamily,
  today: string,
): string {
  switch (bucket) {
    case "failed_autopay": {
      const failure = family.failure;
      if (!failure) return "";
      const parts: string[] = [];
      const reason = humanize(failure.reason);
      if (reason) parts.push(reason);
      parts.push(`attempt ${failure.attempt_count} of ${failure.max_attempts}`);
      parts.push(
        failure.next_retry_on && !failure.disabled
          ? `retries ${formatDateOnly(failure.next_retry_on)}`
          : "no more retries",
      );
      return parts.join(" · ");
    }
    case "past_due": {
      const inv = primaryInvoice(family);
      if (!inv) return "";
      const late = Math.max(daysBetween(inv.due_date, today), 0);
      const parts = [
        `due ${formatDateOnly(inv.due_date)}`,
        `${late} ${late === 1 ? "day" : "days"} late`,
        family.last_reminder_at
          ? `reminded ${formatDateOnly(family.last_reminder_at)}`
          : "never reminded",
      ];
      if (family.invoices.length > 1 || family.leftover_balance_cents > 0) {
        parts.push(`${monthsOwed(family)} months owed`);
      }
      return parts.join(" · ");
    }
    case "awaiting": {
      const inv = primaryInvoice(family);
      if (!inv) return "";
      const delivered = inv.delivery_status === "sent" || inv.delivery_status === "delivered";
      return `due ${formatDateOnly(inv.due_date)} · ${delivered ? "invoice emailed" : "invoice not sent"}`;
    }
    case "autopay_scheduled": {
      const autopay = family.autopay;
      const inv = primaryInvoice(family);
      const chargeOn = autopay?.charge_on ?? inv?.due_date ?? null;
      const parts = [
        autopay?.card_last4 ? `card ••${autopay.card_last4}` : "card on file",
        `charges ${formatDateOnly(chargeOn)} 9:00 AM`,
        autopay?.notice_sent_at
          ? `notice emailed ${formatDateOnly(autopay.notice_sent_at)}`
          : "notice not sent",
      ];
      return parts.join(" · ");
    }
    case "paused": {
      const pause = family.pause;
      if (!pause) return "";
      const parts = [pause.session_title ?? pause.student_name];
      if (pause.resume_on) parts.push(`resumes ${formatDateOnly(pause.resume_on)}`);
      else if (pause.review_on) parts.push(`review ${formatDateOnly(pause.review_on)}`);
      else parts.push("no resume date");
      parts.push(
        family.leftover_balance_cents > 0
          ? `leftover ${formatCents(family.leftover_balance_cents)}`
          : "no balance",
      );
      return parts.join(" · ");
    }
    case "paid": {
      const paid = family.paid;
      if (!paid) return "";
      const method = paymentMethodLabel(paid.method);
      return `${method ? titleCase(method) : "Paid"} · ${formatDateOnly(paid.paid_at)}`;
    }
  }
}

/** Today's calendar date as YYYY-MM-DD in the viewer's local zone. */
export function todayISO(now: Date = new Date()): string {
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/** The current month and the 11 before it, newest first, as YYYY-MM. */
export function periodOptions(now: Date = new Date()): { value: string; label: string }[] {
  const options: { value: string; label: string }[] = [];
  for (let i = 0; i < 12; i += 1) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    const value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    options.push({ value, label: periodLabel(value) });
  }
  return options;
}

/** "September 2026" from "2026-09". */
export function periodLabel(period: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(period);
  if (!match) return period;
  const d = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, 1));
  return d.toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" });
}

/** Case-insensitive match of a search term against parent and student names. */
export function familyMatches(family: AdminCollectionsFamily, term: string): boolean {
  const needle = term.trim().toLowerCase();
  if (!needle) return true;
  const haystack = [
    family.parent_name,
    family.parent_email,
    ...family.students.map((s) => s.name),
    ...family.students.map((s) => s.session_title),
  ]
    .filter((v): v is string => Boolean(v))
    .join(" ")
    .toLowerCase();
  return haystack.includes(needle);
}
