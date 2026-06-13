"use client";

import { ExternalLink, FileText } from "lucide-react";

import type { LessonCard, VideoLink } from "@/components/teaching/types";

/**
 * Lesson card for the coach daily teaching plan.
 *
 * Renders the BWF Shuttle Time lesson guidance (original-wording summary):
 * lesson number + title, goal, collapsible teaching points / equipment /
 * activity / safety, then a footer of YouTube links (card- and level-scoped)
 * plus a non-interactive PDF citation chip.
 */
export function LessonCardView({
  card,
  levelYoutubeLinks = [],
}: {
  card: LessonCard;
  levelYoutubeLinks?: VideoLink[];
}) {
  // Card-scoped YouTube links come from resource_links; combine with the
  // level-scoped links and dedupe by URL (card links win on title).
  const youtube: VideoLink[] = [];
  const seen = new Set<string>();
  for (const r of card.resource_links) {
    if (r.kind === "YOUTUBE" && r.url && !seen.has(r.url)) {
      seen.add(r.url);
      youtube.push({ title: r.title, url: r.url });
    }
  }
  for (const link of levelYoutubeLinks) {
    if (link.url && !seen.has(link.url)) {
      seen.add(link.url);
      youtube.push(link);
    }
  }

  const pdfRefs = card.resource_links.filter((r) => r.kind === "PDF_REFERENCE");
  const hasDetails =
    card.teaching_points.length > 0 ||
    card.equipment.length > 0 ||
    card.activity_summary.trim().length > 0 ||
    card.safety_notes.length > 0;

  return (
    <article
      data-testid={`lesson-card-${card.card_id}`}
      className="rounded-xl border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900"
    >
      <header className="flex items-start gap-3">
        <span
          aria-hidden="true"
          className="mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-rally-base/10 text-sm font-bold text-rally-base"
        >
          {card.lesson_number}
        </span>
        <div className="min-w-0">
          <h3 className="text-base font-semibold leading-tight">
            <span className="sr-only">Lesson {card.lesson_number}: </span>
            {card.title}
          </h3>
          {card.goal_summary && (
            <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-300">
              {card.goal_summary}
            </p>
          )}
        </div>
      </header>

      {hasDetails && (
        <details className="group mt-3" open>
          <summary className="flex min-h-touch cursor-pointer list-none items-center gap-1 text-sm font-medium text-rally-base">
            <span className="transition-transform group-open:rotate-90">›</span>
            Lesson details
          </summary>

          <div className="mt-2 space-y-3">
            {card.teaching_points.length > 0 && (
              <Section title="Teaching points">
                <ul className="list-disc space-y-1 pl-5 text-sm text-neutral-700 dark:text-neutral-300">
                  {card.teaching_points.map((p, i) => (
                    <li key={i}>{p}</li>
                  ))}
                </ul>
              </Section>
            )}

            {card.equipment.length > 0 && (
              <Section title="Equipment">
                <div className="flex flex-wrap gap-1.5">
                  {card.equipment.map((e, i) => (
                    <span
                      key={i}
                      className="rounded-full bg-neutral-100 px-2.5 py-0.5 text-xs text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300"
                    >
                      {e}
                    </span>
                  ))}
                </div>
              </Section>
            )}

            {card.activity_summary.trim().length > 0 && (
              <Section title="Activity">
                <p className="text-sm text-neutral-700 dark:text-neutral-300">
                  {card.activity_summary}
                </p>
              </Section>
            )}

            {card.safety_notes.length > 0 && (
              <Section title="Safety">
                <ul className="list-disc space-y-1 pl-5 text-sm text-amber-700 dark:text-amber-400">
                  {card.safety_notes.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
              </Section>
            )}
          </div>
        </details>
      )}

      {(youtube.length > 0 || pdfRefs.length > 0) && (
        <footer className="mt-3 flex flex-wrap gap-2 border-t border-neutral-100 pt-3 dark:border-neutral-800">
          {youtube.map((link, i) => (
            <a
              key={link.url}
              href={link.url}
              target="_blank"
              rel="noopener noreferrer"
              data-testid={`lesson-card-youtube-${card.card_id}-${i}`}
              className="inline-flex min-h-touch items-center gap-1.5 rounded-lg border border-red-200 bg-red-50 px-3 text-xs font-medium text-red-700 hover:bg-red-100 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
            >
              <ExternalLink className="size-3.5" aria-hidden="true" />
              {link.title || "Watch video"}
            </a>
          ))}

          {pdfRefs.map((ref, i) => (
            <span
              key={i}
              data-testid={`lesson-card-pdf-${card.card_id}-${i}`}
              title="Reference only — not a link"
              className="inline-flex min-h-touch items-center gap-1.5 rounded-lg bg-neutral-100 px-3 text-xs font-medium text-neutral-500 dark:bg-neutral-800 dark:text-neutral-400"
            >
              <FileText className="size-3.5" aria-hidden="true" />
              {ref.title}
            </span>
          ))}
        </footer>
      )}
    </article>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-neutral-400">
        {title}
      </p>
      {children}
    </div>
  );
}
