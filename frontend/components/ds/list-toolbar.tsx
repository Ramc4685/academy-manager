"use client";

/**
 * Issue #897: ONE toolbar for the People lists.
 *
 * Students, Families and Users each hand-rolled a filter row and a search
 * box, so the same control was an ink `role="tab"` pill on one page, a slate
 * pill inside a bordered group on the second and a `rounded-full` neutral
 * pill on the third — three components by accident, never a shared baseline
 * that drifted. The Students toolbar is the reference shape and moves here
 * verbatim; each page keeps its own state, its own query wiring and its own
 * ARIA vocabulary (Students is a real single-select tab strip that switches
 * what the list shows; the other two are independent toggles).
 *
 * Presentational only: nothing here fetches, filters or remembers anything.
 */

import { RefreshCw, Search } from "lucide-react";
import type { ReactNode } from "react";

/** The bar itself: filters on the left, search (and any actions) on the right. */
export function ListToolbar({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`flex flex-col gap-3 border-b border-neutral-200 bg-white px-5 py-4 dark:border-neutral-800 dark:bg-neutral-950 lg:flex-row lg:items-center lg:justify-between ${className}`}
    >
      {children}
    </div>
  );
}

/**
 * #865: ten chips wrapped onto three lines on a phone and pushed the first
 * row below the fold. One scrolling row below `md:`; the desktop wrap is
 * unchanged.
 */
export function FilterBar({
  children,
  label,
  testId,
  variant = "group",
}: {
  children: ReactNode;
  /** Accessible name for the set, e.g. "People by lifecycle". */
  label: string;
  testId?: string;
  /** "tablist" only where the chips really switch what the list shows. */
  variant?: "tablist" | "group";
}) {
  return (
    <div
      role={variant === "tablist" ? "tablist" : "group"}
      aria-label={label}
      data-testid={testId}
      className="-mx-1 flex items-center gap-2 overflow-x-auto px-1 md:mx-0 md:flex-wrap md:overflow-visible md:px-0"
    >
      {children}
    </div>
  );
}

/**
 * #847: 32px tall was under the 44px touch minimum on the one control an
 * admin taps most on a phone. Desktop keeps 32.
 */
export function FilterChip({
  active,
  onClick,
  label,
  count = null,
  testId,
  countTestId,
  variant = "toggle",
}: {
  active: boolean;
  onClick: () => void;
  label: ReactNode;
  /** Rendered beside the label when the page knows the number. */
  count?: number | null;
  testId?: string;
  countTestId?: string;
  /**
   * `aria-selected` belongs to a tab inside a tablist and is not valid on a
   * plain button; `aria-pressed` is the toggle vocabulary for the rest.
   */
  variant?: "tab" | "toggle";
}) {
  const ariaProps =
    variant === "tab"
      ? ({ role: "tab", "aria-selected": active } as const)
      : ({ "aria-pressed": active } as const);

  return (
    <button
      type="button"
      {...ariaProps}
      data-testid={testId}
      onClick={onClick}
      className={`inline-flex min-h-touch shrink-0 items-center gap-2 whitespace-nowrap rounded-md px-3 font-body text-[13px] font-semibold transition md:h-8 md:min-h-0 ${
        active ? "bg-rally-ink text-white" : "bg-transparent text-rally-muted hover:bg-neutral-100"
      }`}
    >
      {label}
      {count !== null && (
        <span
          data-testid={countTestId}
          className={`font-mono text-[11px] tabular-nums ${
            active ? "text-white/70" : "text-rally-subtle"
          }`}
        >
          {count}
        </span>
      )}
    </button>
  );
}

export function ToolbarSearch({
  id,
  label,
  value,
  onChange,
  placeholder,
  busy = false,
  busyLabel = "Refreshing",
}: {
  id: string;
  /** Visually hidden, so the box needs no heading of its own. */
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  busy?: boolean;
  busyLabel?: string;
}) {
  return (
    <div className="relative min-w-0 lg:w-[320px]">
      <label htmlFor={id} className="sr-only">
        {label}
      </label>
      <Search
        aria-hidden="true"
        className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-rally-muted"
      />
      <input
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="h-10 w-full rounded-md border border-neutral-200 bg-white pl-9 pr-9 font-body text-sm text-rally-base outline-none transition placeholder:text-rally-subtle focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
      />
      {busy && (
        <RefreshCw
          aria-label={busyLabel}
          className="absolute right-3 top-1/2 size-4 -translate-y-1/2 animate-spin text-rally-muted"
        />
      )}
    </div>
  );
}
