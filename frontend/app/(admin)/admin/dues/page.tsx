"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { listDuesFollowup, sendDuesReminders } from "@/lib/api/admin";

function money(cents: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);
}

export default function AdminDuesPage() {
  const queryClient = useQueryClient();
  const { data, isLoading, isError } = useQuery({
    queryKey: ["admin", "dues-followup"],
    queryFn: listDuesFollowup,
  });
  const reminderMutation = useMutation({
    mutationFn: sendDuesReminders,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["admin", "dues-followup"] }),
  });

  const parents = data?.parents ?? [];
  const totalDue = parents.reduce((sum, parent) => sum + parent.total_due_cents, 0);

  return (
    <section data-testid="admin-dues" className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Dues followup</h1>
          <p className="mt-1 text-sm text-neutral-500">
            Parents with pending manual invoices grouped for follow-up.
          </p>
        </div>
        <button
          type="button"
          onClick={() => reminderMutation.mutate()}
          disabled={reminderMutation.isPending || parents.length === 0}
          className="min-h-touch rounded-md bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
        >
          {reminderMutation.isPending ? "Checking..." : "Send reminders"}
        </button>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <Metric label="Parents" value={String(parents.length)} />
        <Metric label="Open invoices" value={String(parents.reduce((sum, row) => sum + row.pending_count, 0))} />
        <Metric label="Total due" value={money(totalDue)} />
      </div>

      {reminderMutation.data && (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          {reminderMutation.data.blocked
            ? reminderMutation.data.reason
            : `${reminderMutation.data.sent} reminder(s) sent.`}
        </div>
      )}

      {isError ? (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load dues follow-up.
        </p>
      ) : isLoading ? (
        <Skeleton />
      ) : parents.length === 0 ? (
        <p className="text-sm text-neutral-500">No pending dues.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="border-b border-neutral-200 text-left text-neutral-500 dark:border-neutral-800">
                <th className="px-4 py-3 font-medium">Parent</th>
                <th className="px-4 py-3 font-medium">Email</th>
                <th className="px-4 py-3 font-medium text-right">Open invoices</th>
                <th className="px-4 py-3 font-medium text-right">Due</th>
              </tr>
            </thead>
            <tbody>
              {parents.map((parent) => (
                <tr key={parent.parent_id} className="border-b border-neutral-100 last:border-0 dark:border-neutral-800">
                  <td className="px-4 py-3">
                    <div className="font-medium">{parent.parent_name || "Parent"}</div>
                    <div className="font-mono text-xs text-neutral-500">{parent.parent_id}</div>
                  </td>
                  <td className="px-4 py-3 text-neutral-600 dark:text-neutral-300">{parent.email ?? "-"}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{parent.pending_count}</td>
                  <td className="px-4 py-3 text-right font-medium tabular-nums">
                    {money(parent.total_due_cents)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900">
      <p className="text-xs font-medium uppercase tracking-wide text-neutral-500">{label}</p>
      <p className="mt-2 text-xl font-semibold tabular-nums">{value}</p>
    </div>
  );
}

function Skeleton() {
  return (
    <div className="space-y-2">
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-14 animate-pulse rounded-lg bg-neutral-100 dark:bg-neutral-800" />
      ))}
    </div>
  );
}
