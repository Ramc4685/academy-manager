"use client";

/**
 * Issue #847: ONE two-line phone row for every admin list.
 *
 * Line 1 is who or what the row is, plus the single status or amount that
 * decides what to do about it. Line 2 is the secondary facts, wrapped rather
 * than truncated. Row actions live behind a 44x44 menu trigger at the trailing
 * edge, so a thumb can reach them without a sideways scroll.
 *
 * The rule for callers: pass the values the desktop table already derived
 * (`DuesChip`, `lifecycleLabel`, `formatCents`, the shared `lib/people-status`
 * chips). The phone row is a second LAYOUT, never a second derivation — if it
 * re-computed status or money it would eventually disagree with the table, and
 * an admin would have two different answers for the same person.
 *
 * Callers mount this instead of their `<table>` below `md:` — see
 * `lib/use-is-phone.ts` for why the choice is made in JS and not with
 * `hidden md:block` / `md:hidden` twins.
 */

import Link from "next/link";
import type { Route } from "next";
import { MoreVertical } from "lucide-react";
import type { ReactNode } from "react";

import { OverflowMenu, type MenuItem } from "./menu";

// Typed routes: callers build these from an id, so they cast with `as Route`
// the way `app/(admin)/admin/families/page.tsx` already does.
type Href = Route;

export function PhoneList({
  children,
  className = "",
  ...rest
}: {
  children: ReactNode;
  className?: string;
  "aria-label"?: string;
  "data-testid"?: string;
}) {
  return (
    <ul
      role="list"
      aria-label={rest["aria-label"]}
      data-testid={rest["data-testid"]}
      className={`divide-y divide-rally-line ${className}`}
    >
      {children}
    </ul>
  );
}

export interface PhoneListRowProps {
  /** Line 1, leading: who or what this row is. */
  title: ReactNode;
  /** Makes the title a link to the row's own page. */
  href?: Href;
  /** `data-testid` for the title link, so a spec can assert where it goes. */
  titleTestId?: string;
  /** Line 1, trailing: the one status chip or amount that ranks this row. */
  primary?: ReactNode;
  /** Line 2: the secondary facts. */
  secondary?: ReactNode;
  /** An avatar or icon before the text. */
  leading?: ReactNode;
  /** Row actions, behind a 44px menu trigger. Empty or omitted renders none. */
  actions?: MenuItem[];
  /** Accessible name for the actions trigger, e.g. "Actions for Amit Rao". */
  actionsLabel?: string;
  actionsTestId?: string;
  "data-testid"?: string;
}

export function PhoneListRow({
  title,
  href,
  titleTestId,
  primary,
  secondary,
  leading,
  actions,
  actionsLabel = "Row actions",
  actionsTestId,
  ...rest
}: PhoneListRowProps) {
  const titleNode = href ? (
    <Link
      href={href}
      data-testid={titleTestId}
      className="block rounded font-semibold text-rally-base hover:underline focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600"
    >
      {title}
    </Link>
  ) : (
    <span className="font-semibold text-rally-base">{title}</span>
  );

  return (
    <li
      data-testid={rest["data-testid"]}
      className="flex items-start gap-3 px-4 py-3"
    >
      {leading ? <div className="shrink-0 pt-1">{leading}</div> : null}
      <div className="min-w-0 flex-1">
        {/* min-h-touch, so the title line alone is a 44px target even on a
            row that carries no secondary line. */}
        <div className="flex min-h-touch flex-wrap items-center justify-between gap-x-3 gap-y-1">
          <div className="min-w-0 break-words text-[15px] leading-5">{titleNode}</div>
          {primary ? <div className="shrink-0">{primary}</div> : null}
        </div>
        {secondary ? (
          <div className="mt-1 space-y-1 text-[13px] leading-5 text-rally-muted">
            {secondary}
          </div>
        ) : null}
      </div>
      {actions && actions.length > 0 ? (
        <OverflowMenu
          className="shrink-0"
          items={actions}
          triggerLabel={actionsLabel}
          triggerTestId={actionsTestId}
          trigger={
            <span className="flex min-h-touch min-w-touch items-center justify-center rounded-md text-rally-muted hover:bg-rally-paper">
              <MoreVertical className="size-5" aria-hidden="true" />
            </span>
          }
        />
      ) : null}
    </li>
  );
}
