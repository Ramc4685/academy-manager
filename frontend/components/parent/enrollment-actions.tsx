"use client";

import { Button } from "@/components/ds/button";
import { OverflowMenu, type MenuItem } from "@/components/ds/menu";

/**
 * Pause / Cancel for one enrollment on the parent Children card.
 *
 * At 390 px two inline buttons squeezed the class name into a 17 px sliver,
 * so phones get one "Manage enrollment" menu instead; wider screens keep the
 * inline buttons. Both paths call the same handlers, which open the same
 * confirmation steps, so eligibility and confirmation rules are unchanged.
 */
export function enrollmentActionItems({
  canRequestPause,
  canRequestCancel,
  onPause,
  onCancel,
}: {
  canRequestPause: boolean;
  canRequestCancel: boolean;
  onPause: () => void;
  onCancel: () => void;
}): MenuItem[] {
  const items: MenuItem[] = [];
  if (canRequestPause) items.push({ key: "pause", label: "Pause enrollment", onSelect: onPause });
  if (canRequestCancel) {
    items.push({ key: "cancel", label: "Cancel enrollment…", onSelect: onCancel, danger: true });
  }
  return items;
}

export function EnrollmentActions({
  enrollmentId,
  sessionTitle,
  childName,
  canRequestPause,
  canRequestCancel,
  pausing,
  onPause,
  onCancel,
}: {
  enrollmentId: string;
  sessionTitle: string;
  childName: string;
  canRequestPause: boolean;
  canRequestCancel: boolean;
  pausing: boolean;
  onPause: () => void;
  onCancel: () => void;
}) {
  const items = enrollmentActionItems({ canRequestPause, canRequestCancel, onPause, onCancel });
  if (items.length === 0) return null;

  return (
    <>
      <div className="sm:hidden">
        <OverflowMenu
          items={items}
          align="end"
          triggerLabel={`Manage enrollment for ${childName} in ${sessionTitle}`}
          triggerTestId={`enrollment-manage-${enrollmentId}`}
          trigger={
            <span className="inline-flex min-h-[44px] items-center justify-center rounded-lg border border-rally-line bg-white px-3 text-xs font-semibold text-rally-ink hover:bg-rally-paper">
              Manage enrollment
            </span>
          }
        />
      </div>
      <div className="hidden shrink-0 items-center gap-2 sm:flex">
        {canRequestPause && (
          <Button
            variant="secondary"
            size="sm"
            data-testid={`enrollment-pause-${enrollmentId}`}
            aria-expanded={pausing}
            onClick={onPause}
          >
            Pause enrollment
          </Button>
        )}
        {canRequestCancel && (
          <Button variant="danger" size="sm" onClick={onCancel}>
            Cancel enrollment…
          </Button>
        )}
      </div>
    </>
  );
}
