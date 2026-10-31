/**
 * JSON-LD for the public academy page (brief section 4): one
 * SportsActivityLocation, a Course per listed class with its weekly schedule
 * and, when prices are public, an Offer; plus FAQPage.
 *
 * No personal data: coach names are left out on purpose (they are on the
 * visible page, but structured data is harvested and cached by third
 * parties), as are availability (changes hourly) and any contact detail.
 */

import { safeHttpsUrl } from "./format";
import { allClasses, faqEntries } from "./page-model";
import type { PublicAcademyPage, PublicClass } from "./types";

const SCHEMA_DAYS: Record<string, string> = {
  mon: "https://schema.org/Monday",
  tue: "https://schema.org/Tuesday",
  wed: "https://schema.org/Wednesday",
  thu: "https://schema.org/Thursday",
  fri: "https://schema.org/Friday",
  sat: "https://schema.org/Saturday",
  sun: "https://schema.org/Sunday",
};

type JsonLd = Record<string, unknown>;

function compact(value: JsonLd): JsonLd {
  const out: JsonLd = {};
  for (const [key, v] of Object.entries(value)) {
    if (v === null || v === undefined || v === "") continue;
    if (Array.isArray(v) && v.length === 0) continue;
    out[key] = v;
  }
  return out;
}

function hhmm(value: string | null): string | null {
  if (!value) return null;
  const match = /^(\d{1,2}):(\d{2})/.exec(value.trim());
  return match ? `${match[1].padStart(2, "0")}:${match[2]}` : null;
}

function courseFor(cls: PublicClass, page: PublicAcademyPage, providerId: string): JsonLd {
  const byDay = cls.days_of_week
    .map((d) => SCHEMA_DAYS[d.trim().toLowerCase().slice(0, 3)])
    .filter((d): d is string => Boolean(d));
  const schedule = compact({
    "@type": "Schedule",
    byDay,
    repeatFrequency: byDay.length > 0 ? "P1W" : null,
    startDate: cls.starts_on,
    startTime: hhmm(cls.start_time),
    endTime: hhmm(cls.end_time),
    scheduleTimezone: cls.timezone ?? page.academy.timezone,
  });
  const offers =
    page.page.show_price && cls.price
      ? {
          "@type": "Offer",
          price: (cls.price.amount_cents / 100).toFixed(2),
          priceCurrency: page.academy.currency,
          category: cls.price.period,
        }
      : null;
  return compact({
    "@type": "Course",
    name: cls.title,
    description: cls.description ?? cls.title,
    provider: { "@id": providerId },
    hasCourseInstance: compact({
      "@type": "CourseInstance",
      courseMode: "onsite",
      courseSchedule: schedule,
      location: cls.location ?? cls.venue_address ?? page.academy.venue.address,
    }),
    offers,
  });
}

export function buildPublicPageJsonLd(page: PublicAcademyPage, origin: string): JsonLd[] {
  const url = `${origin}/`;
  const providerId = `${url}#academy`;
  const location = compact({
    "@context": "https://schema.org",
    "@type": "SportsActivityLocation",
    "@id": providerId,
    name: page.academy.name,
    url,
    logo: safeHttpsUrl(page.academy.logo_url),
    address: page.academy.venue.address,
  });
  const graph: JsonLd[] = [location];
  const classes = allClasses(page);
  if (classes.length > 0) {
    graph.push({
      "@context": "https://schema.org",
      "@type": "ItemList",
      itemListElement: classes.map((cls, index) => ({
        "@type": "ListItem",
        position: index + 1,
        item: courseFor(cls, page, providerId),
      })),
    });
  }
  const faq = faqEntries(page);
  if (faq.length > 0) {
    graph.push({
      "@context": "https://schema.org",
      "@type": "FAQPage",
      mainEntity: faq.map((entry) => ({
        "@type": "Question",
        name: entry.question,
        acceptedAnswer: { "@type": "Answer", text: entry.answer },
      })),
    });
  }
  return graph;
}

/**
 * Serialise for a `<script type="application/ld+json">`. `<`, `>` and `&`
 * are escaped so tenant text such as "</script>" can never close the tag.
 */
export function serializeJsonLd(value: unknown): string {
  return JSON.stringify(value)
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
}
