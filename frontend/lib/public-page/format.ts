/**
 * Pure label formatting for the public academy page. No colour math lives
 * here (colours come pre-computed from the backend) and nothing reads the
 * clock, so every function is deterministic and unit tested in
 * `format.test.ts`.
 */

import type {
  PublicAgeBand,
  PublicClass,
  PublicPrice,
  PublicPricePeriod,
  PublicSeats,
} from "./types";

const PERIOD_LABELS: Record<PublicPricePeriod, string> = {
  month: "per month",
  class: "per class",
  term: "per term",
};

/** "per month" / "per class" / "per term"; unknown periods read as "per month". */
export function formatPricePeriod(period: string | null | undefined): string {
  if (period && period in PERIOD_LABELS) return PERIOD_LABELS[period as PublicPricePeriod];
  return PERIOD_LABELS.month;
}

/**
 * Amount in the academy's currency: "$120", "$45.50", "Free". Whole amounts
 * drop the cents so a class row reads like a price list, not an invoice.
 */
export function formatAmount(amountCents: number, currency: string): string {
  if (!Number.isFinite(amountCents) || amountCents <= 0) return "Free";
  const whole = amountCents % 100 === 0;
  const value = amountCents / 100;
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: (currency || "USD").toUpperCase(),
      minimumFractionDigits: whole ? 0 : 2,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    // An unknown ISO code must never crash the page.
    return `${value.toFixed(whole ? 0 : 2)} ${currency}`.trim();
  }
}

export interface PriceLabel {
  amount: string;
  /** Empty for a free class: "Free per month" reads wrong. */
  period: string;
}

/** Null when the academy hides prices or the class carries none. */
export function formatPrice(price: PublicPrice | null, currency: string): PriceLabel | null {
  if (!price) return null;
  const amount = formatAmount(price.amount_cents, currency);
  return { amount, period: amount === "Free" ? "" : formatPricePeriod(price.period) };
}

export type SeatTone = "ok" | "few" | "queue";

export interface SeatLabel {
  text: string;
  tone: SeatTone;
  /** A full class: its row offers the waitlist instead of Register or a trial. */
  full: boolean;
}

/**
 * The availability ticket. Bands, never counts, except the "few" band's own
 * small number ("2 spots left"), which the backend sends only when 3 or fewer
 * remain. Null when the academy hides availability.
 */
export function formatSeatBand(seats: PublicSeats | null): SeatLabel | null {
  if (!seats) return null;
  switch (seats.band) {
    case "open":
      return { text: "Open", tone: "ok", full: false };
    case "few": {
      const left = seats.seats_left;
      if (typeof left === "number" && left > 0) {
        return { text: left === 1 ? "1 spot left" : `${left} spots left`, tone: "few", full: false };
      }
      return { text: "A few spots left", tone: "few", full: false };
    }
    case "waitlist":
      return { text: "Full, join waitlist", tone: "queue", full: true };
    default:
      return null;
  }
}

/** "Ages 6 to 8", "Ages 18 and up", "Up to age 12"; null when unknown. */
export function formatAgeBand(band: PublicAgeBand | null | undefined): string | null {
  if (!band) return null;
  const min = typeof band.min_age === "number" ? band.min_age : null;
  const max = typeof band.max_age === "number" ? band.max_age : null;
  if (min !== null && max !== null) {
    return min === max ? `Age ${min}` : `Ages ${min} to ${max}`;
  }
  if (min !== null) return `Ages ${min} and up`;
  if (max !== null) return `Up to age ${max}`;
  return null;
}

/** The widest age span across every band given, for the hero facts line. */
export function ageSpan(bands: Array<PublicAgeBand | null | undefined>): PublicAgeBand | null {
  let min: number | null = null;
  let max: number | null = null;
  let openEnded = false;
  let seen = false;
  for (const band of bands) {
    if (!band) continue;
    if (typeof band.min_age === "number") {
      min = min === null ? band.min_age : Math.min(min, band.min_age);
      seen = true;
    }
    if (typeof band.max_age === "number") {
      max = max === null ? band.max_age : Math.max(max, band.max_age);
      seen = true;
    } else if (typeof band.min_age === "number") {
      openEnded = true;
    }
  }
  if (!seen) return null;
  return { min_age: min, max_age: openEnded ? null : max };
}

const DAY_SHORT: Record<string, string> = {
  mon: "Mon",
  tue: "Tue",
  wed: "Wed",
  thu: "Thu",
  fri: "Fri",
  sat: "Sat",
  sun: "Sun",
};

const DAY_LONG: Record<string, string> = {
  mon: "Monday",
  tue: "Tuesday",
  wed: "Wednesday",
  thu: "Thursday",
  fri: "Friday",
  sat: "Saturday",
  sun: "Sunday",
};

function dayKey(day: string): string {
  return day.trim().toLowerCase().slice(0, 3);
}

/** "Saturday", "Mon & Wed", "Tue, Thu & Sat". Unknown tokens pass through. */
export function formatDays(days: string[]): string {
  const cleaned = days.map((d) => d.trim()).filter(Boolean);
  if (cleaned.length === 0) return "";
  if (cleaned.length === 1) return DAY_LONG[dayKey(cleaned[0])] ?? cleaned[0];
  const short = cleaned.map((d) => DAY_SHORT[dayKey(d)] ?? d);
  return `${short.slice(0, -1).join(", ")} & ${short[short.length - 1]}`;
}

interface ParsedTime {
  hour12: number;
  minute: string;
  meridiem: "AM" | "PM";
}

function parseTime(value: string | null | undefined): ParsedTime | null {
  if (!value) return null;
  const match = /^(\d{1,2}):(\d{2})/.exec(value.trim());
  if (!match) return null;
  const hour = Number(match[1]);
  if (hour > 23) return null;
  return {
    hour12: hour % 12 === 0 ? 12 : hour % 12,
    minute: match[2],
    meridiem: hour < 12 ? "AM" : "PM",
  };
}

function clock(t: ParsedTime, withMeridiem: boolean): string {
  const base = t.minute === "00" ? `${t.hour12}` : `${t.hour12}:${t.minute}`;
  return withMeridiem ? `${base} ${t.meridiem}` : base;
}

/** "4:30 to 5:30 PM", "11 AM to 12:15 PM", "6 PM"; "" when unknown. */
export function formatTimeRange(start: string | null, end: string | null): string {
  const s = parseTime(start);
  const e = parseTime(end);
  if (s && e) {
    const sameHalf = s.meridiem === e.meridiem;
    return `${clock(s, !sameHalf)} to ${clock(e, true)}`;
  }
  if (s) return clock(s, true);
  return "";
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "Sat, Oct 3" from "2026-10-03", computed in UTC so it never shifts a day. */
export function formatClassDate(isoDate: string | null): string {
  if (!isoDate) return "";
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(isoDate);
  if (!match) return "";
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  if (Number.isNaN(date.getTime())) return "";
  const weekday = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][date.getUTCDay()];
  return `${weekday}, ${MONTHS[date.getUTCMonth()]} ${date.getUTCDate()}`;
}

/** The row's "when" line: weekly days, or the one-off date. */
export function formatWhen(cls: Pick<PublicClass, "days_of_week" | "starts_on">): string {
  const days = formatDays(cls.days_of_week ?? []);
  if (days) return days;
  return formatClassDate(cls.starts_on) || "Schedule to be confirmed";
}

/** How many class meetings a week the listed classes add up to. */
export function weeklyClassCount(classes: Array<Pick<PublicClass, "days_of_week">>): number {
  return classes.reduce((sum, cls) => sum + (cls.days_of_week?.length ?? 0), 0);
}

/** Truncate on a character budget with an ellipsis (brief section 7 ranges). */
export function truncate(value: string, max: number): string {
  const text = value.trim();
  if (text.length <= max) return text;
  return `${text.slice(0, Math.max(0, max - 1)).trimEnd()}…`;
}

/** Two-letter monogram for an academy with no logo: "Riverside Shuttle Club" -> "RS". */
export function monogram(name: string): string {
  const words = name
    .split(/\s+/)
    .map((w) => w.replace(/[^\p{L}\p{N}]/gu, ""))
    .filter(Boolean);
  if (words.length === 0) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

/** Accept only a 3- or 6-digit hex colour (defence in depth on backend values). */
export function safeHexColor(value: string | null | undefined, fallback: string): string {
  if (typeof value === "string" && /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(value.trim())) {
    return value.trim();
  }
  return fallback;
}

/** Only an absolute https URL may be used as an image or link target. */
export function safeHttpsUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.toString() : null;
  } catch {
    return null;
  }
}

/** Plain "Open in maps" search link; no embedded map, no API key. */
export function mapsSearchUrl(address: string): string {
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(address)}`;
}
