"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { listDuesFollowup, sendDuesReminders } from "@/lib/api/admin";
import { useAdminAction } from "@/components/admin/admin-action-slot";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { BigNum, Overline } from "@/components/ds/typography";

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
    mutationFn: (parentIds: string[] | undefined) =>
      sendDuesReminders(parentIds ? { parent_ids: parentIds } : {}),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["admin", "dues-followup"] }),
  });
  const { mutate: sendReminderBatch, isPending: sendingReminders } = reminderMutation;
  const [selectedParentIds, setSelectedParentIds] = useState<string[]>([]);

  const parents = data?.parents ?? [];
  const selectedCount = selectedParentIds.length;
  const totalDue = parents.reduce((sum, parent) => sum + parent.total_due_cents, 0);
  const visibleParentIds = parents.map((parent) => parent.parent_id);
  const allSelected = visibleParentIds.length > 0 && visibleParentIds.every((id) => selectedParentIds.includes(id));

  const topbarAction = useMemo(
    () => (
      <Button
        variant="primary"
        onClick={() => sendReminderBatch(selectedCount ? selectedParentIds : undefined)}
        disabled={sendingReminders || parents.length === 0}
      >
        {sendingReminders
          ? "Sending..."
          : selectedCount
            ? `Email ${selectedCount} selected`
            : "Email listed parents"}
      </Button>
    ),
    [parents.length, selectedCount, selectedParentIds, sendReminderBatch, sendingReminders]
  );
  useAdminAction(topbarAction);

  return (
    <section data-testid="admin-dues" className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-3">
        <Metric label="Parents" value={String(parents.length)} />
        <Metric label="Open invoices" value={String(parents.reduce((sum, row) => sum + row.pending_count, 0))} />
        <Metric label="Total due" value={money(totalDue)} />
      </div>

      {reminderMutation.data && (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          {reminderMutation.data.blocked
            ? reminderMutation.data.reason
            : `${reminderMutation.data.sent} dues reminder email(s) sent.`}
          {reminderMutation.data.generated_invoice_artifacts > 0 &&
            ` ${reminderMutation.data.generated_invoice_artifacts} invoice artifact(s) generated.`}
        </div>
      )}

      {isError ? (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load dues follow-up.
        </p>
      ) : isLoading ? (
        <Skeleton />
      ) : parents.length === 0 ? (
        <p data-testid="admin-dues-empty" className="text-sm text-neutral-500">No pending dues.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
          <p className="border-b border-neutral-200 px-4 py-3 text-sm text-neutral-600 dark:border-neutral-800 dark:text-neutral-300">
            Select parents to send targeted reminders. With none selected, the reminder uses the full pending-dues list.
          </p>
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="border-b border-neutral-200 text-left text-neutral-500 dark:border-neutral-800">
                <th className="px-4 py-3">
                  <input
                    type="checkbox"
                    aria-label="Select all parents"
                    checked={allSelected}
                    onChange={(event) => {
                      setSelectedParentIds(event.target.checked ? visibleParentIds : []);
                    }}
                  />
                </th>
                <th className="px-4 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Parent</th>
                <th className="px-4 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Email</th>
                <th className="px-4 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted text-right">Open invoices</th>
                <th className="px-4 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted text-right">Due</th>
              </tr>
            </thead>
            <tbody>
              {parents.map((parent) => (
                <tr key={parent.parent_id} data-testid={`admin-dues-row-${parent.parent_id}`} className="border-b border-neutral-100 last:border-0 dark:border-neutral-800">
                  <td className="px-4 py-3">
                    <input
                      type="checkbox"
                      aria-label={`Select ${parent.parent_name || parent.email || "parent"}`}
                      checked={selectedParentIds.includes(parent.parent_id)}
                      onChange={(event) => {
                        setSelectedParentIds((current) =>
                          event.target.checked
                            ? Array.from(new Set([...current, parent.parent_id]))
                            : current.filter((id) => id !== parent.parent_id)
                        );
                      }}
                    />
                  </td>
                  <td className="px-4 py-3">
                    <div className="font-medium">{parent.parent_name || "Parent"}</div>
                  </td>
                  <td className="px-4 py-3 text-neutral-600 dark:text-neutral-300">{parent.email ?? "-"}</td>
                  <td className="px-4 py-3 text-right font-mono tabular-nums">{parent.pending_count}</td>
                  <td className="px-4 py-3 text-right font-mono tabular-nums font-medium">
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
    <Card p={16}>
      <Overline>{label}</Overline>
      <div className="mt-2">
        <BigNum size={24}>{value}</BigNum>
      </div>
    </Card>
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
