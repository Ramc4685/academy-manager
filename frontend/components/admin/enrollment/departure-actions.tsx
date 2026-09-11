"use client";

/**
 * Shared enrollment action set for departures (#696).
 *
 * Extracted from the inline button rows in
 * `app/(admin)/admin/sessions/[id]/RosterPanel.tsx` and `dialogs.tsx` so the
 * class roster, the student profile Sessions panel, and (once #697 ships
 * Hold/Return) other surfaces render one consistent set of actions with one
 * vocabulary.
 *
 * Vocabulary (owner-settled, see the departures design contract):
 *   Transfer, Hold, Return, Drop, Delete — never "Cancel", which is reserved
 *   for classes and dates, not a child. Pause/Resume are a *transitional*
 *   group: today's pause releases the seat and a hold (#697) does not, so
 *   relabelling Pause/Resume to Hold/Return now would misrepresent seat
 *   safety. They render in a visually separate group until #697 removes
 *   them.
 *
 * Stateless: this component owns no dialog state and makes no request. The
 * caller supplies exactly which actions are available (`actions`) and reacts
 * to `onAction`. Owner-only actions (Delete) are never inferred here from
 * status — the caller decides what's available; this component only decides
 * how to gate an action the caller *did* include: disabled + a hint for a
 * non-owner, hidden for nobody.
 */

import type { ReactNode } from "react";

import { OverflowMenu, type MenuItem } from "@/components/ds/menu";
import { Button } from "@/components/ds/button";
import { OwnerOnlyHint } from "@/components/admin/owner-context";

import { resolveDepartureActions } from "./departure-actions.logic";
import type { DepartureAction } from "./departure-actions.logic";

export {
  DEPARTURE_ACTION_LABEL,
  holdActionsFor,
  resolveDepartureActions,
  type DepartureAction,
  type ResolvedDepartureAction,
} from "./departure-actions.logic";

export interface DepartureActionsProps {
  enrollmentId: string;
  studentName: string;
  status: string;
  actions: DepartureAction[];
  layout: "menu" | "inline";
  isOwner: boolean;
  onAction: (action: DepartureAction, enrollmentId: string) => void;
  /**
   * Navigation entry pinned to the top of the overflow menu (#713). The roster
   * uses it for "Pathway", which used to be a standalone button beside the
   * kebab and cost every row ~100px of width on a phone. Ignored when the
   * caller renders no overflow menu.
   */
  leadingLink?: { key: string; label: ReactNode; href: MenuItem["href"] };
  className?: string;
}

export function DepartureActions({
  enrollmentId,
  studentName,
  actions,
  layout,
  isOwner,
  onAction,
  leadingLink,
  className = "",
}: DepartureActionsProps) {
  const resolved = resolveDepartureActions(actions, { isOwner, layout });
  const inline = resolved.filter((entry) => !entry.inOverflow);
  const overflow = resolved.filter((entry) => entry.inOverflow);

  const overflowItems: MenuItem[] = [
    ...(leadingLink ? [{ key: leadingLink.key, label: leadingLink.label, href: leadingLink.href }] : []),
    ...overflow.map((entry) => ({
      key: entry.action,
      label: entry.label,
      disabled: entry.disabled,
      danger: entry.danger,
      hint: entry.ownerGated ? <OwnerOnlyHint /> : undefined,
      onSelect: () => onAction(entry.action, enrollmentId),
    })),
  ];

  return (
    <div
      className={`flex flex-wrap items-center justify-end gap-1.5 ${className}`}
      data-testid={`departure-actions-${enrollmentId}`}
    >
      {inline.map((entry) => (
        <Button
          key={entry.action}
          variant={entry.danger ? "danger" : "secondary"}
          size="sm"
          disabled={entry.disabled}
          title={entry.ownerGated ? "Only the academy owner can do this" : undefined}
          onClick={() => onAction(entry.action, enrollmentId)}
          aria-label={`${entry.label} ${studentName}`}
        >
          {entry.label}
        </Button>
      ))}
      {overflowItems.length > 0 && (
        <OverflowMenu
          items={overflowItems}
          trigger={
            <span
              aria-label={`More actions for ${studentName}`}
              className="inline-flex min-h-9 min-w-9 items-center justify-center rounded-md border border-rally-line bg-white px-2 py-1.5 text-rally-ink shadow-sm hover:bg-neutral-50"
            >
              &#8942;
            </span>
          }
        />
      )}
    </div>
  );
}
