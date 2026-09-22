"use client";

import { useId, useState, type ReactNode } from "react";

import { useIsDesktop } from "@/lib/use-is-desktop";

/**
 * A named, collapsible group of month-close cards (issue #862).
 *
 * The month-close page used to be one flat run of ~20 equal-weight cards —
 * 8,950px on a phone — with no way to skip past the part you were not there
 * for. Each group now collapses behind a disclosure button, using the same
 * button + `aria-expanded` pattern the page already uses for odd rows and
 * aging buckets rather than a new primitive.
 *
 * NOT a `Card`: the groups hold cards, and wrapping them in another card
 * doubles every border. The header is its own bordered bar and the body is
 * the existing cards, unchanged, at their normal width.
 */
interface CollapsibleSectionProps {
  /** Stable slug; drives `month-close-section-<id>` test ids. */
  id: string;
  title: string;
  /** One line saying what is inside, so a collapsed group is still scannable. */
  summary: string;
  children: ReactNode;
}

export function CollapsibleSection({ id, title, summary, children }: CollapsibleSectionProps) {
  const bodyId = `${useId()}-body`;
  const isDesktop = useIsDesktop();
  /**
   * `null` until the reader touches it, so the default follows the viewport:
   * collapsed on a phone, open on a desktop where the height was never the
   * problem. `useIsDesktop` reports `false` during hydration, so a desktop
   * section mounts collapsed for one paint and then opens — deliberate, and
   * why the group must not latch the first value into `useState`.
   */
  const [override, setOverride] = useState<boolean | null>(null);
  const open = override ?? isDesktop;

  return (
    <section data-testid={`month-close-section-${id}`}>
      <h2>
        <button
          type="button"
          onClick={() => setOverride(!open)}
          aria-expanded={open}
          aria-controls={bodyId}
          data-testid={`month-close-section-${id}-toggle`}
          className="flex w-full items-center justify-between gap-3 rounded-xl border border-rally-line bg-white px-5 py-4 text-left hover:bg-rally-line/20 focus:outline-none focus-visible:ring-2 focus-visible:ring-rally-cobalt-600/40"
        >
          <span>
            <span className="block font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
              {title}
            </span>
            <span className="mt-1 block text-sm text-rally-subtle">{summary}</span>
          </span>
          <span className="shrink-0 text-sm font-medium text-rally-cobalt-600">
            {open ? "Hide" : "Show"}
          </span>
        </button>
      </h2>
      {/*
       * The region stays in the DOM so `aria-controls` always resolves, but
       * its contents unmount when collapsed: that is what takes the height
       * out of the page, and it keeps Recharts from measuring a zero-sized
       * container inside a hidden group.
       */}
      <div
        id={bodyId}
        hidden={!open}
        data-testid={`month-close-section-${id}-body`}
        className="mt-4 space-y-4"
      >
        {open ? children : null}
      </div>
    </section>
  );
}
