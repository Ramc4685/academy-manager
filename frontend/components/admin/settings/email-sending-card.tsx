"use client";

import { useQuery } from "@tanstack/react-query";

import { getAdminAcademy } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";

/**
 * Read-only "Email" section of Settings -> Integrations (Settings overhaul
 * Phase 3 PR 11). Shows how mail is sent today: through CourtMastr's mail
 * service under the academy's name. The values come from the same academy
 * record the Academy profile tab edits; nothing here writes.
 */
export function EmailSendingCard() {
  const query = useQuery({
    queryKey: queryKeys.admin.academy(),
    queryFn: () => getAdminAcademy(),
  });
  const academy = query.data;
  const senderName = academy?.email_sender_name?.trim() || academy?.display_name || "Your academy";
  const explicitReplyTo = academy?.email_reply_to?.trim() || null;
  const effectiveReplyTo = academy?.effective_reply_to?.trim() || explicitReplyTo;
  const replyToSource = academy?.effective_reply_to_source ?? (explicitReplyTo ? "reply_to" : null);

  return (
    <Card p={24} className="max-w-3xl" data-testid="integrations-email-card">
      <Overline>Email</Overline>
      {query.isLoading ? (
        <div className="mt-5 h-16 animate-pulse rounded-md bg-rally-paper" />
      ) : (
        <div className="mt-5 space-y-3">
          <p className="text-sm text-rally-ink">
            Email goes out through CourtMastr&apos;s mail service under your academy name.
          </p>
          <dl className="grid gap-2 text-sm sm:grid-cols-[10rem_1fr]">
            <dt className="text-rally-muted">Sent as</dt>
            <dd data-testid="integrations-email-sender" className="font-medium text-rally-ink">
              {senderName}
            </dd>
            <dt className="text-rally-muted">Replies go to</dt>
            <dd data-testid="integrations-email-reply-to" className="font-medium text-rally-ink">
              {effectiveReplyTo
                ? replyToSource === "support_email"
                  ? `${effectiveReplyTo} (support email)`
                  : effectiveReplyTo
                : "Not set. Replies use each email's default."}
            </dd>
          </dl>
          <p className="text-sm text-rally-muted">
            Change the name and reply address in Academy profile. Using your own email account is
            coming later.
          </p>
        </div>
      )}
    </Card>
  );
}
