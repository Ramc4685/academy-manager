import { apiFetch } from "./client";

/** One self-service account deletion in this academy (mobile M5, D4). */
export interface AccountDeletion {
  request_id: string;
  user_id: string;
  /** Every id the person was known by; a family page matches its parent id here. */
  aliases: string[];
  display_name: string;
  status: "scheduled" | "running" | "completed";
  requested_at: string;
  execute_after: string;
  completed_at: string | null;
  attempts: number;
  failing_step: string | null;
}

export function fetchAccountDeletions(): Promise<{ deletions: AccountDeletion[] }> {
  return apiFetch<{ deletions: AccountDeletion[] }>("/admin/account-deletions", { method: "GET" });
}

/** The request covering this family, matched by any of its ids. */
export function deletionForFamily(
  rows: AccountDeletion[] | undefined,
  familyIds: (string | null | undefined)[],
): AccountDeletion | undefined {
  const ids = new Set(familyIds.filter((id): id is string => Boolean(id)));
  return rows?.find((row) => row.user_id && [row.user_id, ...row.aliases].some((a) => ids.has(a)));
}

const day = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });

/** One-line status an admin reads on the family page and in the list. */
export function deletionSummary(row: AccountDeletion): string {
  if (row.status === "completed") {
    return `Deleted by the parent on ${day(row.requested_at)}. Personal details were removed on ${day(row.completed_at ?? row.execute_after)}.`;
  }
  if (row.status === "running") {
    return `Deleted by the parent on ${day(row.requested_at)}. Personal details are being removed now.`;
  }
  const stuck = row.attempts > 0 ? ` Removal has failed ${row.attempts} time${row.attempts === 1 ? "" : "s"} and is being retried.` : "";
  return `Deleted by the parent on ${day(row.requested_at)}. Personal details are removed on ${day(row.execute_after)}; until then support can still restore the account.${stuck}`;
}
