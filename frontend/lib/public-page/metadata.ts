/**
 * Per-tenant `<head>` for the public academy page: title, description,
 * canonical, Open Graph and Twitter card (pointing at the generated
 * `/og-card`), and robots (index only a published page with classes).
 */

import type { Metadata } from "next";

import { ageSpan, formatAgeBand, truncate } from "./format";
import { allClasses, describePublishedPage, isIndexable } from "./page-model";
import type { PublicAcademyPage, PublicPageResult } from "./types";

export const OG_CARD_PATH = "/og-card";
const TITLE_MAX = 70;
const DESCRIPTION_MAX = 155;

export function publishedDescription(page: PublicAcademyPage): string {
  const view = describePublishedPage(page);
  const classes = allClasses(page);
  const span = formatAgeBand(
    ageSpan([...page.programs.map((p) => p.age_band), ...classes.map((c) => c.age_band)]),
  );
  const parts: string[] = [];
  if (!view.hasClasses) {
    parts.push(`${page.academy.name} is getting its new timetable ready.`);
  } else {
    parts.push(
      span
        ? `Classes at ${page.academy.name} for ${span.toLowerCase()}.`
        : `Classes at ${page.academy.name}.`,
    );
    parts.push("See days, times and prices.");
  }
  if (view.trialsOpen && view.hasClasses) parts.push("First class free.");
  if (page.academy.venue.address) parts.push(page.academy.venue.address);
  return truncate(parts.join(" "), DESCRIPTION_MAX);
}

export function publishedTitle(page: PublicAcademyPage): string {
  const view = describePublishedPage(page);
  const suffix = view.trialsOpen && view.hasClasses ? "classes and a free trial" : "classes and prices";
  return truncate(`${page.academy.name}: ${suffix}`, TITLE_MAX);
}

/** Null for the product host (the root layout's metadata stays). */
export function buildPublicPageMetadata(
  result: PublicPageResult,
  origin: string,
): Metadata | null {
  const url = `${origin}/`;
  switch (result.kind) {
    case "platform":
    case "unknown_host":
      return null;
    case "unavailable":
      return { title: "Class page", robots: { index: false, follow: false } };
    case "not_published":
      return {
        title: truncate(result.page.academy.name, TITLE_MAX),
        description: `${result.page.academy.name} parent sign in.`,
        robots: { index: false, follow: false },
        alternates: { canonical: url },
      };
    case "published": {
      const title = publishedTitle(result.page);
      const description = publishedDescription(result.page);
      const image = {
        url: `${origin}${OG_CARD_PATH}`,
        width: 1200,
        height: 630,
        alt: result.page.academy.name,
      };
      const index = isIndexable(result);
      return {
        title,
        description,
        applicationName: result.page.academy.name,
        alternates: { canonical: url },
        robots: { index, follow: index },
        openGraph: {
          type: "website",
          url,
          siteName: result.page.academy.name,
          title,
          description,
          images: [image],
        },
        twitter: {
          card: "summary_large_image",
          title,
          description,
          images: [image.url],
        },
      };
    }
  }
}
