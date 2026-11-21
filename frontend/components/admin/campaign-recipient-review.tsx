import type { EmailCampaignPreview, EmailCampaignPreviewExclusion } from "@/lib/api/admin";

/**
 * #1031: the confirmation's read-only review of who a campaign reaches and
 * who it skips, from the same resolution and send-time rules the send uses.
 */
const REASON_COPY: Record<string, string> = {
  missing_email: "No email address on file",
  duplicate_address: "Same address as another recipient (gets one copy)",
  suppressed: "Address is not receiving email (bounced or reported)",
  unsubscribed: "Unsubscribed from campaign emails",
};

export function exclusionReasonCopy(reason: EmailCampaignPreviewExclusion["reason"]): string {
  return REASON_COPY[reason] ?? "Will not receive this email";
}

export function CampaignRecipientReview({ preview }: { preview: EmailCampaignPreview }) {
  return (
    <div className="space-y-3" data-testid="campaign-recipient-review">
      <p className="font-semibold text-rally-ink">
        Recipients ({preview.recipient_count})
      </p>
      <ul className="max-h-40 divide-y divide-rally-line overflow-y-auto rounded-md border border-rally-line bg-rally-paper">
        {preview.recipients.map((r) => (
          <li key={r.email} className="flex flex-wrap items-baseline justify-between gap-x-3 px-3 py-1.5">
            <span className="text-rally-ink">
              {r.display_name ?? r.email}
              {r.is_family_contact && (
                <span className="ml-2 font-mono text-[10px] uppercase text-rally-muted">Family contact</span>
              )}
            </span>
            <span className="break-all text-[12px] text-rally-subtle">{r.email}</span>
          </li>
        ))}
      </ul>
      {preview.exclusions.length > 0 && (
        <>
          <p className="font-semibold text-rally-ink">
            Not receiving this ({preview.exclusions.length})
          </p>
          <ul className="max-h-32 divide-y divide-rally-line overflow-y-auto rounded-md border border-rally-line">
            {preview.exclusions.map((e, i) => (
              <li key={`${e.email ?? e.display_name ?? ""}-${i}`} className="px-3 py-1.5">
                <span className="text-rally-ink">{e.display_name ?? e.email ?? "Unnamed contact"}</span>
                <span className="block text-[12px] text-rally-subtle">{exclusionReasonCopy(e.reason)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
