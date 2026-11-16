"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  getReferralEmailPreview,
  getReferrals,
  type ReferralRow,
} from "@/lib/api/admin";
import { formatCents } from "@/lib/money";
import { queryKeys } from "@/lib/query/keys";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";

const REASONS: Record<NonNullable<ReferralRow["reason"]>, string> = {
  unknown_code: "Code not recognised",
  self_referral: "Same family",
  existing_family: "Already a family here",
  yearly_cap_reached: "Referrer reached the yearly limit",
};

function day(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleDateString() : "";
}

/** The state column: what happened, or what the row is waiting for. */
export function referralState(row: ReferralRow): string {
  if (row.status === "granted") return `Credited ${day(row.granted_at)}`;
  if (row.status === "ineligible") {
    return `Not eligible: ${row.reason ? REASONS[row.reason] : "unknown"}`;
  }
  if (row.grant_due_at) return `Paid; credit due ${day(row.grant_due_at)}`;
  return "Waiting for the first paid invoice";
}

/**
 * Settings -> Billing rules -> Referrals (L9 C2). Read only: the referrals
 * the daily sweep has recorded, and the two emails the programme would send
 * (nothing sends until the owner signs off on the copy).
 */
export function ReferralsCard() {
  const query = useQuery({
    queryKey: queryKeys.admin.referrals(),
    queryFn: getReferrals,
  });
  const [previewOpen, setPreviewOpen] = useState(false);
  const preview = useQuery({
    queryKey: queryKeys.admin.referralEmailPreview(),
    queryFn: getReferralEmailPreview,
    enabled: previewOpen,
  });
  const rows = query.data?.referrals ?? [];

  return (
    <Card p={24} className="max-w-3xl" data-testid="referrals-card">
      <Overline>Referrals</Overline>
      {query.isError ? (
        <p className="mt-2 text-sm text-red-700" role="alert">
          Could not load referrals.
        </p>
      ) : rows.length === 0 ? (
        <p className="mt-2 text-sm text-rally-muted">
          No referrals yet. They appear here the day after a referred family
          registers.
        </p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-rally-muted">
              <tr>
                <th className="py-1 pr-3 font-medium">Referred by</th>
                <th className="py-1 pr-3 font-medium">New family</th>
                <th className="py-1 pr-3 font-medium">Credit</th>
                <th className="py-1 font-medium">State</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.referral_id}
                  className="border-t border-rally-line"
                  data-testid="referral-row"
                >
                  <td className="py-1.5 pr-3 text-rally-ink">
                    {row.referrer_name || row.referral_code}
                  </td>
                  <td className="py-1.5 pr-3 text-rally-ink">
                    {row.referred_name || "Unknown"}
                  </td>
                  <td className="py-1.5 pr-3 text-rally-muted">
                    {row.referrer_credit_cents != null
                      ? formatCents(row.referrer_credit_cents)
                      : ""}
                  </td>
                  <td className="py-1.5 text-rally-muted">
                    {referralState(row)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <details
        className="mt-4"
        onToggle={(event) => setPreviewOpen(event.currentTarget.open)}
      >
        <summary className="cursor-pointer text-sm font-medium text-rally-ink">
          Email copy (not sent; needs your sign-off)
        </summary>
        {preview.isError && (
          <p className="mt-2 text-sm text-red-700" role="alert">
            Could not load the email preview.
          </p>
        )}
        {(preview.data?.emails ?? []).map((email) => (
          <div key={email.key} className="mt-3">
            <p className="text-sm font-semibold text-rally-ink">
              {email.subject}
            </p>
            <iframe
              title={email.subject}
              sandbox=""
              srcDoc={email.html}
              className="mt-1 h-48 w-full rounded border border-rally-line bg-white"
            />
          </div>
        ))}
      </details>
    </Card>
  );
}
