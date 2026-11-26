"use client";

/**
 * S27: what a transfer does, stated before it happens. Shared by the roster's
 * Transfer dialog and the student page's Move dialog so the two never drift.
 *
 * The billing sentence claims only what the transfer route guarantees: the
 * move commits first, then billing is asked to follow it, and a billing
 * failure is recorded on the enrollment's history instead of failing the move
 * (`_sync_move_billing` in enrollment `admin_writes.py`). The email sentence
 * names the one family email a move can send: a stale autopay notice resent
 * when the price rises (`apply_enrollment_move.py`, `notice_resender`).
 */

import type { AdminSessionView } from "@/lib/api/admin";
import { formatSessionOccurrence, formatWeeklyPattern } from "@/lib/format/session-display";

export interface TransferSide {
  title: string;
  schedule: string;
  /** Monthly price in cents; null or undefined with `unpriced` means no price set. */
  amountCents?: number | null;
  unpriced?: boolean;
  /** "3 of 12 seats taken"; omitted when unknown. */
  seats?: string;
}

export function sessionTransferSide(session: AdminSessionView): TransferSide {
  return {
    title: session.title,
    schedule: formatWeeklyPattern(session) || formatSessionOccurrence(session, null),
    amountCents: session.amount_cents,
    unpriced: session.unpriced ?? session.amount_cents == null,
    seats: `${session.enrolled_count} of ${session.capacity} seats taken`,
  };
}

const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

export function formatMonthlyPrice(side: Pick<TransferSide, "amountCents" | "unpriced">): string {
  if (side.unpriced || side.amountCents == null) return "No price set";
  return `${money.format(side.amountCents / 100)}/month`;
}

/** A tick is required when the price changes or the target has no price. */
export function transferNeedsAcknowledgement(from: TransferSide, to: TransferSide): boolean {
  return formatMonthlyPrice(from) !== formatMonthlyPrice(to) || formatMonthlyPrice(to) === "No price set";
}

function SideCard({ label, side }: { label: string; side: TransferSide }) {
  return (
    <div className="rounded-md border border-rally-line p-3">
      <p className="font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">{label}</p>
      <p className="mt-1 text-sm font-semibold text-rally-ink">{side.title}</p>
      {side.schedule && <p className="text-xs text-rally-muted">{side.schedule}</p>}
      <p className="mt-1 text-sm text-rally-ink" data-testid={`transfer-${label.toLowerCase()}-price`}>
        {formatMonthlyPrice(side)}
      </p>
      {side.seats && <p className="text-xs text-rally-subtle">{side.seats}</p>}
    </div>
  );
}

export function TransferConsequences({
  from,
  to,
  acknowledged,
  onAcknowledge,
}: {
  from: TransferSide;
  /** Null until a target class is picked. */
  to: TransferSide | null;
  acknowledged: boolean;
  onAcknowledge: (next: boolean) => void;
}) {
  const needsAck = to != null && transferNeedsAcknowledgement(from, to);
  return (
    <div className="space-y-3" data-testid="transfer-consequences">
      {to && (
        <div className="grid gap-2 sm:grid-cols-2">
          <SideCard label="From" side={from} />
          <SideCard label="To" side={to} />
        </div>
      )}
      {needsAck && to && (
        <label
          data-testid="transfer-price-ack"
          className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900"
        >
          <input
            type="checkbox"
            required
            className="mt-0.5 h-4 w-4"
            checked={acknowledged}
            onChange={(e) => onAcknowledge(e.target.checked)}
          />
          <span>
            {formatMonthlyPrice(to) === "No price set"
              ? `The new class has no price yet (${formatMonthlyPrice(from)} to No price set). This month's invoice drops the classes left in the old class, and the new class is not billed until the owner sets a price.`
              : `The monthly price changes from ${formatMonthlyPrice(from)} to ${formatMonthlyPrice(to)}.`}{" "}
            Move anyway.
          </span>
        </label>
      )}
      <p className="text-xs text-rally-subtle">
        Emailed: the coaches of both classes and the academy&apos;s admins. The family gets no
        transfer email; if this month&apos;s invoice was already sent and the price goes up, they
        get a corrected payment notice.
      </p>
      <p className="text-xs text-rally-subtle">
        The move happens first. Billing is then asked to move this month&apos;s invoice to the new
        price from the effective date; if it cannot, the move still stands and the failure is
        recorded in the enrollment history, so check the family&apos;s invoices afterwards.
      </p>
    </div>
  );
}
