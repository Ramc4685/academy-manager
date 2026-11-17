"use client";

/**
 * L11 item 3: who in this academy is not getting email. Read-only. The block
 * list is shared by every academy, so the page never says why or since when an
 * address is blocked; clearing one is a platform support action.
 */

import { useQuery } from "@tanstack/react-query";

import { getDeliveryProblems, type DeliveryProblemsView } from "@/lib/api/admin";
import { emailFailureLabel } from "@/lib/format/email-failure";
import { queryKeys } from "@/lib/query/keys";

export function DeliveryProblemsList({ data }: { data: DeliveryProblemsView }) {
  if (data.suppressed_emails.length === 0 && data.failed.length === 0) {
    return (
      <p data-testid="delivery-problems-empty">
        No delivery problems. Every email is getting through.
      </p>
    );
  }
  return (
    <div data-testid="delivery-problems">
      {data.suppressed_emails.length > 0 && (
        <>
          <h3>Not receiving email</h3>
          <ul>
            {data.suppressed_emails.map((email) => (
              <li key={email} data-testid="delivery-problem-suppressed">
                <span>{email}</span> · <span>This address is not receiving email</span>
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
                <span>{emailFailureLabel(d.failed_reason)}</span>
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
