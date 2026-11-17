"use client";

/**
 * L11 item 3: who in this academy is not getting email. Read-only. The block
 * list is shared by every academy, so the reason and date show only when the
 * problem came from this academy's own mail; clearing an address is a
 * platform support action.
 */

import { useQuery } from "@tanstack/react-query";

import { getDeliveryProblems, type DeliveryProblemsView } from "@/lib/api/admin";
import { formatAcademyDate } from "@/lib/format/academy-time";
import { queryKeys } from "@/lib/query/keys";

const REASON_LABEL: Record<string, string> = {
  hard_bounce: "Bounced (mailbox does not exist)",
  complaint: "Marked our email as spam",
  manual: "Blocked by support",
};

export function DeliveryProblemsList({ data }: { data: DeliveryProblemsView }) {
  if (data.suppressed.length === 0 && data.failed.length === 0) {
    return (
      <p data-testid="delivery-problems-empty">
        No delivery problems. Every email is getting through.
      </p>
    );
  }
  return (
    <div data-testid="delivery-problems">
      {data.suppressed.length > 0 && (
        <>
          <h3>Not receiving email</h3>
          <ul>
            {data.suppressed.map((row) => (
              <li key={row.email} data-testid="delivery-problem-suppressed">
                <span>{row.email}</span> ·{" "}
                {row.reason ? (
                  <>
                    <span>{REASON_LABEL[row.reason] ?? row.reason}</span>
                    {row.last_seen_at && (
                      <span> · since {formatAcademyDate(row.last_seen_at, null)}</span>
                    )}
                  </>
                ) : (
                  <span>This address is not receiving email</span>
                )}
              </li>
            ))}
          </ul>
          <p>To send to one of these addresses again, contact support.</p>
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
  const query = useQuery({
    queryKey: queryKeys.admin.deliveryProblems(),
    queryFn: getDeliveryProblems,
  });
  if (query.isLoading) return <p>Loading delivery problems…</p>;
  if (query.isError || !query.data) return <p role="alert">Could not load delivery problems.</p>;
  return <DeliveryProblemsList data={query.data} />;
}
