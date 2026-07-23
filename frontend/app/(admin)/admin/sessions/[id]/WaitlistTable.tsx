"use client";

import { type AdminWaitlistEntry, type WaitlistStatus } from "@/lib/api/admin";

import { Button } from "@/components/ds/button";
import { Chip, type ChipVariant } from "@/components/ds/chip";
import { Th } from "@/components/ds/dialog-chrome";

import { actionCellClass, actionHeaderClass } from "./format";

const WAITLIST_CHIP: Record<WaitlistStatus, { variant: ChipVariant; label: string }> = {
  waiting: { variant: "waitlist", label: "WAITING" },
  promoted: { variant: "enrolled", label: "PROMOTED" },
  skipped: { variant: "expired", label: "SKIPPED" },
  removed: { variant: "expired", label: "REMOVED" },
};

export function WaitlistTable({
  entries,
  onSkip,
  onRemove,
}: {
  entries: AdminWaitlistEntry[];
  onSkip: (id: string) => void;
  onRemove: (id: string) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[620px] text-sm">
        <thead>
          <tr className="border-b border-rally-line text-left">
            <Th>#</Th>
            <Th>Name</Th>
            <Th>Status</Th>
            <Th className={actionHeaderClass}><span className="sr-only">Actions</span></Th>
          </tr>
        </thead>
        <tbody>
          {entries.map((w) => {
            const chip = WAITLIST_CHIP[w.status];
            return (
              <tr
                key={w.waitlist_id}
                data-testid={`waitlist-row-${w.waitlist_id}`}
                className="border-b border-rally-line/60 last:border-0"
              >
                <td className="px-4 py-3 font-mono tabular-nums text-rally-muted">{w.position}</td>
                <td className="px-4 py-3 font-display font-semibold text-rally-ink">{w.full_name}</td>
                <td className="px-4 py-3">
                  <Chip variant={chip.variant} label={chip.label} />
                </td>
                <td className={actionCellClass}>
                  <div className="flex min-w-[140px] flex-wrap items-center justify-end gap-1.5">
                    {w.status === "waiting" && (
                      <Button variant="secondary" size="sm" onClick={() => onSkip(w.waitlist_id)}>
                        Skip
                      </Button>
                    )}
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => onRemove(w.waitlist_id)}
                      aria-label={`Remove ${w.full_name} from waitlist`}
                    >
                      Remove
                    </Button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
