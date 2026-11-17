"use client";

import { Card } from "@/components/ds";
import type { FamilyAccountCredit } from "@/lib/api/admin-families";
import { formatCents, formatInstantDay } from "@/lib/money";

const TYPE_LABEL: Record<string, string> = {
  CLASS_CANCELLATION_CREDIT: "Class called off",
  EARLY_WITHDRAWAL_CREDIT: "Withdrawal",
  MOVE_PRORATION_CREDIT: "Class move",
  MANUAL_CREDIT: "Manual credit",
  REFERRAL_CREDIT: "Referral",
};

/** Only an approved credit with money left comes off the next invoice. */
function creditState(c: FamilyAccountCredit): { label: string; spendable: boolean } {
  if (c.status === "PENDING") return { label: "Waiting for approval", spendable: false };
  if (c.status === "EXPIRED") return { label: "Expired", spendable: false };
  if (c.status === "APPROVED" && c.remaining_amount_cents > 0) {
    return { label: `${formatCents(c.remaining_amount_cents)} left`, spendable: true };
  }
  return { label: "Used", spendable: false };
}

/**
 * #1207: every credit the family holds or held, so the owner can answer "did
 * they get their money back for the 25th?" — what, why, who approved it, what
 * is left, and which invoice it came off. Credits apply to the next invoice by
 * themselves; nothing here moves money.
 */
export function CreditsPanel({ credits, balanceCents }: { credits: unknown; balanceCents: number }) {
  // The e2e catch-all stub answers `{}`; an older backend omits the field.
  const rows: FamilyAccountCredit[] = Array.isArray(credits) ? credits : [];
  if (rows.length === 0 && balanceCents <= 0) return null;
  return (
    <Card p={16} data-testid="family-credits">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-base font-semibold text-rally-ink">Credits</h2>
        <p className="text-sm text-rally-muted" data-testid="family-credit-balance">
          {formatCents(balanceCents)} available for the next invoice
        </p>
      </div>
      {rows.length === 0 ? (
        <p className="mt-2 text-sm text-rally-subtle">No credit history to show.</p>
      ) : (
        <ul className="mt-2 divide-y divide-rally-line">
          {rows.map((c) => (
            <li key={c.credit_id} className="py-3 text-sm" data-testid={`family-credit-${c.credit_id}`}>
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="font-semibold text-rally-ink">
                  {TYPE_LABEL[c.type] ?? "Credit"} · {formatCents(c.amount_cents)}
                </p>
                <p className={creditState(c).spendable ? "text-status-green-800" : "text-rally-muted"}>
                  {creditState(c).label}
                </p>
              </div>
              <p className="mt-0.5 text-rally-muted">{c.reason}</p>
              <p className="mt-0.5 text-xs text-rally-subtle">
                {formatInstantDay(c.created_at)}
                {c.approved_by_name ? ` · by ${c.approved_by_name}` : ""}
                {c.applied_invoices.length > 0 ? ` · applied to ${c.applied_invoices.join(", ")}` : ""}
              </p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
