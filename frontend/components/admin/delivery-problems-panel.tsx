"use client";

/**
 * L11 item 3: who in this academy is not getting email, and why. Suppressions
 * come from provider bounce and complaint reports; only a hard bounce can be
 * cleared here (a complaint means the person marked mail as spam).
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ConfirmActionDialog } from "@/components/admin/confirm-action-dialog";
import { Button } from "@/components/ds/button";
import {
  getDeliveryProblems,
  releaseDeliverySuppression,
  type DeliveryProblemsView,
} from "@/lib/api/admin";
import { formatAcademyDate } from "@/lib/format/academy-time";
import { queryKeys } from "@/lib/query/keys";

const REASON_LABEL: Record<string, string> = {
  hard_bounce: "Bounced (mailbox does not exist)",
  complaint: "Marked our email as spam",
  manual: "Blocked by support",
};

export function DeliveryProblemsList({
  data,
  onClear,
}: {
  data: DeliveryProblemsView;
  onClear: (email: string) => void;
}) {
  if (data.suppressed.length === 0 && data.failed.length === 0) {
    return <p data-testid="delivery-problems-empty">No delivery problems. Every email is getting through.</p>;
  }
  return (
    <div data-testid="delivery-problems">
      {data.suppressed.length > 0 && (
        <>
          <h3>Not receiving email</h3>
          <ul>
            {data.suppressed.map((row) => (
              <li key={row.email} data-testid="delivery-problem-suppressed">
                <span>{row.email}</span> · <span>{REASON_LABEL[row.reason] ?? row.reason}</span> ·{" "}
                <span>since {formatAcademyDate(row.last_seen_at, null)}</span>
                {row.releasable && (
                  <Button size="sm" variant="secondary" onClick={() => onClear(row.email)}>
                    Try again
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
      {data.failed.length > 0 && (
        <>
          <h3>Failed campaign sends</h3>
          <ul>
            {data.failed.map((d) => (
              <li key={d.delivery_id} data-testid="delivery-problem-failed">
                <span>{d.recipient_email ?? "No email on file"}</span> ·{" "}
                <span>{d.failed_reason ?? "Send failed"}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

export function DeliveryProblemsPanel() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: queryKeys.admin.deliveryProblems(),
    queryFn: getDeliveryProblems,
  });
  const [pending, setPending] = useState<string | null>(null);
  const clear = useMutation({
    mutationFn: releaseDeliverySuppression,
    onSuccess: () => {
      setPending(null);
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.deliveryProblems() });
    },
  });

  if (query.isLoading) return <p>Loading delivery problems…</p>;
  if (query.isError || !query.data) return <p role="alert">Could not load delivery problems.</p>;

  return (
    <>
      <DeliveryProblemsList data={query.data} onClear={setPending} />
      <ConfirmActionDialog
        open={pending !== null}
        onOpenChange={(open) => !open && setPending(null)}
        overline="Delivery problems"
        title="Send to this address again?"
        subject={pending}
        consequence="We will start emailing this address again. If it bounces again it is blocked again automatically."
        confirmLabel="Try again"
        confirmVariant="primary"
        pending={clear.isPending}
        error={clear.error ? clear.error.message : null}
        onConfirm={() => pending && clear.mutate(pending)}
      />
    </>
  );
}
