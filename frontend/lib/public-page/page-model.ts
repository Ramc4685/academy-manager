/**
 * Turns the public API answer into what the root route renders. Pure: the
 * network call lives in `server-fetch.ts`, so every branch here is unit
 * tested without a server.
 */

import { formatPricePeriod, formatSeatBand } from "./format";
import type {
  PublicAcademyNotPublished,
  PublicAcademyPage,
  PublicClass,
  PublicPageResult,
  PublicProgram,
} from "./types";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasBrand(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value.name === "string" &&
    typeof value.brand_fill === "string" &&
    typeof value.brand_on_color === "string"
  );
}

/**
 * Map the HTTP answer to a render decision.
 *
 * 404 is the backend's single "no academy serves this host" answer (unknown,
 * foreign-in-single-academy, suspended and cancelled all collapse into it at
 * the middleware), so it is the unknown-host state. Anything else that is not
 * a well-formed 200 is "unavailable": the page shows a plain retry notice,
 * never a blank page and never somebody else's data.
 */
export function classifyPublicAcademyResponse(status: number, body: unknown): PublicPageResult {
  if (status === 404) return { kind: "unknown_host" };
  if (status !== 200 || !isRecord(body)) return { kind: "unavailable" };
  if (body.state === "not_published" && hasBrand(body.academy)) {
    return { kind: "not_published", page: body as unknown as PublicAcademyNotPublished };
  }
  if (
    body.state === "published" &&
    hasBrand(body.academy) &&
    isRecord(body.page) &&
    Array.isArray(body.programs) &&
    Array.isArray(body.ungrouped_classes)
  ) {
    return { kind: "published", page: body as unknown as PublicAcademyPage };
  }
  return { kind: "unavailable" };
}

/** A program heading with its classes; ungrouped classes get one plain group. */
export interface ClassGroup {
  key: string;
  name: string;
  description: string | null;
  level: string | null;
  program: PublicProgram | null;
  classes: PublicClass[];
}

export function classGroups(page: PublicAcademyPage): ClassGroup[] {
  const groups: ClassGroup[] = page.programs
    .filter((program) => program.classes.length > 0)
    .map((program) => ({
      key: `program-${program.public_id}`,
      name: program.name,
      description: program.description,
      level: program.level,
      program,
      classes: program.classes,
    }));
  if (page.ungrouped_classes.length > 0) {
    groups.push({
      key: "ungrouped",
      name: groups.length > 0 ? "More classes" : "Classes",
      description: null,
      level: null,
      program: null,
      classes: page.ungrouped_classes,
    });
  }
  return groups;
}

export function allClasses(page: PublicAcademyPage): PublicClass[] {
  return [...page.programs.flatMap((program) => program.classes), ...page.ungrouped_classes];
}

export interface PrimaryAction {
  label: string;
  href: string;
}

export interface PublishedView {
  hasClasses: boolean;
  /** Every listed class shows the waitlist band (availability shown). */
  allFull: boolean;
  trialsOpen: boolean;
  primary: PrimaryAction;
  /** Distinct coach display names, in first-listed order. */
  coaches: string[];
  pricePeriodLabel: string;
}

export const TRIAL_ANCHOR = "#trial";
export const CLASSES_ANCHOR = "#classes";

/**
 * The page's state machine (brief section 7): classes open, some or all full,
 * no classes published, trial requests closed.
 */
export function describePublishedPage(page: PublicAcademyPage): PublishedView {
  const classes = allClasses(page);
  const hasClasses = classes.length > 0;
  const bands = classes.map((cls) => formatSeatBand(cls.seats));
  const allFull = hasClasses && bands.every((band) => band?.full === true);
  const trialsOpen = page.page.trials_open === true;

  let primary: PrimaryAction;
  if (!trialsOpen) {
    primary = hasClasses
      ? { label: "See open classes", href: CLASSES_ANCHOR }
      : { label: "Parent login", href: "/login" };
  } else if (!hasClasses) {
    primary = { label: "Tell me when classes open", href: TRIAL_ANCHOR };
  } else if (allFull) {
    primary = { label: "Join the waitlist", href: TRIAL_ANCHOR };
  } else {
    primary = { label: "Book a free trial", href: TRIAL_ANCHOR };
  }

  const coaches: string[] = [];
  for (const cls of classes) {
    const name = cls.coach_name?.trim();
    if (name && !coaches.includes(name)) coaches.push(name);
  }

  return {
    hasClasses,
    allFull,
    trialsOpen,
    primary,
    coaches,
    pricePeriodLabel: formatPricePeriod(page.page.price_period_default),
  };
}

/** Search engines index only a published page that lists classes. */
export function isIndexable(result: PublicPageResult): boolean {
  return result.kind === "published" && allClasses(result.page).length > 0;
}

export interface FaqEntry {
  question: string;
  answer: string;
}

/**
 * Phase 1 FAQ: fixed copy that states only what the product itself does.
 * The brief seeds FAQ from each class's `what_to_bring` and `absence_policy`,
 * but the public DTO does not carry those yet (flagged in the release note).
 */
export function faqEntries(page: PublicAcademyPage): FaqEntry[] {
  const entries: FaqEntry[] = [];
  if (page.page.trials_open) {
    entries.push({
      question: "What happens at a free trial?",
      answer:
        "The player joins one session of a class at their level. There is no charge, and nothing is booked or paid until you decide to register.",
    });
  }
  entries.push(
    {
      question: "How do we register?",
      answer:
        "Create a parent account, add the player and choose a class. Registration is online and takes a few minutes.",
    },
    {
      question: "How does payment work?",
      answer: `Prices are shown ${formatPricePeriod(page.page.price_period_default)} unless a class says otherwise. You pay online through the parent account once you have registered.`,
    },
    {
      question: "What if a class is full?",
      answer:
        "A full class shows “Full, join waitlist”. Places open up as families move on, and waiting costs nothing.",
    },
  );
  return entries;
}
