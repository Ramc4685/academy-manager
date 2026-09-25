"use client";

import { type AdminWaitlistEntry, type WaitlistStatus } from "@/lib/api/admin";

import { Button } from "@/components/ds/button";
import { Chip, type ChipVariant } from "@/components/ds/chip";
import { Th } from "@/components/ds/dialog-chrome";
import { offerExpiryLabel } from "@/lib/admin/waitlist-offer";

import { actionCellClass, actionHeaderClass } from "./format";

const WAITLIST_CHIP: Record<WaitlistStatus, { variant: ChipVariant; label: string }> = {
  waiting: { variant: "waitlist", label: "WAITING" },
  offered: { variant: "offered", label: "SEAT OFFERED" },
  expired: { variant: "expired", label: "EXPIRED" },
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
                <td className="px-4 py-3 font-mono tabular-nums text-rally-muted">
                  {w.status === "offered" ? "—" : w.position}
                </td>
                <td className="px-4 py-3 font-display font-semibold text-rally-ink">{w.full_name}</td>
                <td className="px-4 py-3">
                  <Chip variant={chip.variant} label={chip.label} />
                  {w.status === "offered" && offerExpiryLabel(w.offer_expires_at) && (
                    <div
                      className="mt-1 text-[12px] text-rally-muted"
                      data-testid={`waitlist-offer-expiry-${w.waitlist_id}`}
                    >
                      {offerExpiryLabel(w.offer_expires_at)}
                    </div>
                  )}
                </td>
                <td className={`${actionCellClass} bg-white`}>
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
                      aria-label={
                        w.status === "offered"
                          ? `Withdraw the seat offered to ${w.full_name}`
                          : `Remove ${w.full_name} from waitlist`
                      }
                    >
                      {w.status === "offered" ? "Withdraw offer" : "Remove"}
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
