"use client";

/**
 * Admin Billing Health (#235).
 *
 * Surfaces the #224 app-owned billing infrastructure to admins:
 * - reconciliation run history (scheduler health)
 * - open failed autopay payments, with one-click retry
 * - quarantined webhook events, with replay
 * Plus a per-invoice payment-attempt timeline.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";

import {
  chargeAdminInvoiceAutopay,
  fetchFailedPaymentAttempts,
  fetchInvoiceAttempts,
  fetchReconciliationRuns,
  listBillingWebhookEvents,
  replayWebhookEvent,
  triggerReconciliation,
  type BillingPaymentAttempt,
  type FailedPaymentRow,
  type ReconciliationRun,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";

import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Chip, type ChipVariant } from "@/components/ds/chip";
import { BigNum, Overline } from "@/components/ds/typography";

function formatCents(cents: number): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(
    cents / 100,
  );
}

function formatTimestamp(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function relativeFromNow(iso: string | null): string {
  if (!iso) return "never";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "never";
  const mins = Math.max(0, Math.round((Date.now() - then) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} hr ago`;
  return `${Math.round(hrs / 24)} d ago`;
}

function truncate(value: string, max = 14): string {
  return value.length > max ? `${value.slice(0, max)}…` : value;
}

function attemptChip(status: string): { variant: ChipVariant; label: string } {
  if (status === "succeeded") return { variant: "paid", label: "SUCCEEDED" };
  if (status === "requires_action") return { variant: "pending", label: "ACTION" };
  return { variant: "failed", label: status.replace(/_/g, " ").toUpperCase() };
}

function runStatusDot(run: ReconciliationRun): string {
  if (run.quarantined > 0 || run.failed > 0) return "#dc2626"; // red
  if (run.repaired > 0) return "#d97706"; // amber
  return "#16a34a"; // green
}

export default function BillingHealthPage() {
  const queryClient = useQueryClient();
  const [attemptsInvoice, setAttemptsInvoice] = useState<FailedPaymentRow | null>(null);
  const [retryResult, setRetryResult] = useState<Record<string, string>>({});
  const [replayState, setReplayState] = useState<Record<string, string>>({});

  const runsQuery = useQuery({
    queryKey: queryKeys.admin.reconciliationRuns(),
    queryFn: () => fetchReconciliationRuns(),
    refetchInterval: 30_000,
  });
  const failedQuery = useQuery({
    queryKey: queryKeys.admin.failedAttempts(),
    queryFn: () => fetchFailedPaymentAttempts(),
  });
  const quarantinedQuery = useQuery({
    queryKey: queryKeys.admin.quarantinedEvents(),
    queryFn: () => listBillingWebhookEvents({ status: "quarantined", limit: 50 }),
  });

  const runs = runsQuery.data?.runs ?? [];
  const failedRows = failedQuery.data?.rows ?? [];
  const quarantined = quarantinedQuery.data?.events ?? [];
  const latestRun = runs[0];

  const invalidateAll = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.admin.reconciliationRuns() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.admin.failedAttempts() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.admin.quarantinedEvents() });
  };

  const reconcileMutation = useMutation({
    mutationFn: () => triggerReconciliation(),
    onSuccess: invalidateAll,
  });

  const retryMutation = useMutation({
    mutationFn: (invoiceId: string) => chargeAdminInvoiceAutopay(invoiceId),
    onSuccess: (result, invoiceId) => {
      setRetryResult((prev) => ({
        ...prev,
        [invoiceId]: result.success
          ? "Charged successfully"
          : `${result.decline_code ?? result.status}`,
      }));
      invalidateAll();
    },
    onError: (err: Error, invoiceId) => {
      setRetryResult((prev) => ({ ...prev, [invoiceId]: err.message ?? "Retry failed" }));
    },
  });

  const replayMutation = useMutation({
    mutationFn: (eventId: string) => replayWebhookEvent(eventId),
    onSuccess: (_result, eventId) => {
      setReplayState((prev) => ({ ...prev, [eventId]: "Replayed — processing" }));
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.quarantinedEvents() });
    },
    onError: (err: Error, eventId) => {
      setReplayState((prev) => ({ ...prev, [eventId]: err.message ?? "Replay failed" }));
    },
  });

  const healthy = failedRows.length === 0 && quarantined.length === 0;

  return (
    <div className="space-y-6 p-4 sm:p-6" data-testid="billing-health-page">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-[-0.01em]">Billing Health</h1>
          <p className="mt-1 text-sm text-rally-muted">
            Last reconciliation run: {relativeFromNow(latestRun?.finished_at ?? null)}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ${
              healthy ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"
            }`}
            data-testid="billing-health-status"
          >
            ● {healthy ? "System healthy" : "Needs attention"}
          </span>
          <Button
            variant="primary"
            size="sm"
            onClick={() => reconcileMutation.mutate()}
            disabled={reconcileMutation.isPending}
            data-testid="run-reconciliation"
          >
            {reconcileMutation.isPending ? "Running…" : "Run reconciliation now"}
          </Button>
        </div>
      </div>

      {reconcileMutation.isError && (
        <Alert tone="red">
          {(reconcileMutation.error as Error)?.message ?? "Reconciliation failed."}
        </Alert>
      )}

      {/* Stat cards */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Metric label="Last Run Scanned" value={String(latestRun?.scanned ?? 0)} />
        <Metric label="Repaired" value={String(latestRun?.repaired ?? 0)} accent="#16a34a" />
        <Metric label="Open Failed Payments" value={String(failedRows.length)} accent="#dc2626" />
        <Metric label="Quarantined Events" value={String(quarantined.length)} accent="#d97706" />
      </div>

      {/* Section 1: Reconciliation runs */}
      <Section title="Reconciliation Runs" hint="Runs every 10 min · showing last 10">
        <Card p={0}>
          {runsQuery.isLoading ? (
            <TableSkeleton />
          ) : runs.length === 0 ? (
            <Empty>No runs recorded yet. The scheduler runs every 10 minutes.</Empty>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-sm" data-testid="reconciliation-runs-table">
                <thead>
                  <tr className="border-b border-rally-line text-left">
                    <Th>Time</Th>
                    <Th align="right">Scanned</Th>
                    <Th align="right">Repaired</Th>
                    <Th align="right">Skipped</Th>
                    <Th align="right">Quarantined</Th>
                    <Th>Notes</Th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run) => (
                    <tr key={run.run_id} className="border-b border-rally-line/60">
                      <Td>
                        <span style={{ color: runStatusDot(run) }}>● </span>
                        {formatTimestamp(run.started_at)}
                      </Td>
                      <Td align="right">{run.scanned}</Td>
                      <Td align="right">{run.repaired}</Td>
                      <Td align="right">{run.skipped}</Td>
                      <Td align="right">{run.quarantined}</Td>
                      <Td>
                        <span className="text-rally-muted">
                          {run.errors.length > 0 ? truncate(String(run.errors[0]), 80) : "—"}
                        </span>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </Section>

      {/* Section 2: Open failed payments */}
      <Section
        title="Open Failed Payments"
        hint="Invoices with no successful payment yet"
        badge={failedRows.length > 0 ? `${failedRows.length} need action` : undefined}
      >
        <Card p={0}>
          {failedQuery.isLoading ? (
            <TableSkeleton />
          ) : failedRows.length === 0 ? (
            <Alert tone="green">All autopay invoices are current.</Alert>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[820px] text-sm" data-testid="failed-payments-table">
                <thead>
                  <tr className="border-b border-rally-line text-left">
                    <Th>Parent · Invoice</Th>
                    <Th align="right">Amount</Th>
                    <Th>Last attempt</Th>
                    <Th>Decline reason</Th>
                    <Th><span className="sr-only">Actions</span></Th>
                  </tr>
                </thead>
                <tbody>
                  {failedRows.map((row) => {
                    const result = retryResult[row.invoice_id];
                    return (
                      <tr
                        key={row.invoice_id}
                        className="border-b border-rally-line/60"
                        data-testid={`failed-row-${row.invoice_id}`}
                      >
                        <Td>
                          <div className="font-medium text-rally-ink">
                            {row.parent_name ?? row.parent_id}
                          </div>
                          <div className="text-xs text-rally-muted">
                            {row.invoice_id} · {row.period}
                          </div>
                        </Td>
                        <Td align="right">{formatCents(row.balance_due_cents)}</Td>
                        <Td>{formatTimestamp(row.latest_attempt_at)}</Td>
                        <Td>
                          {row.latest_decline_code ? (
                            <Chip variant="failed" label={row.latest_decline_code} />
                          ) : (
                            "—"
                          )}
                        </Td>
                        <Td>
                          <div className="flex items-center gap-2">
                            <Button
                              variant="secondary"
                              size="sm"
                              onClick={() => retryMutation.mutate(row.invoice_id)}
                              disabled={retryMutation.isPending}
                              data-testid={`retry-${row.invoice_id}`}
                            >
                              Retry
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => setAttemptsInvoice(row)}
                              data-testid={`view-${row.invoice_id}`}
                            >
                              View →
                            </Button>
                          </div>
                          {result && (
                            <div className="mt-1 text-xs text-rally-muted">{result}</div>
                          )}
                        </Td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </Section>

      {/* Section 3: Quarantined webhook events */}
      <Section
        title="Quarantined Webhook Events"
        badge={quarantined.length > 0 ? `${quarantined.length} pending` : undefined}
      >
        <Card p={0}>
          {quarantinedQuery.isLoading ? (
            <TableSkeleton />
          ) : quarantined.length === 0 ? (
            <Alert tone="green">No quarantined webhook events.</Alert>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-sm" data-testid="quarantined-events-table">
                <thead>
                  <tr className="border-b border-rally-line text-left">
                    <Th>Event ID</Th>
                    <Th>Type</Th>
                    <Th>Reason quarantined</Th>
                    <Th><span className="sr-only">Action</span></Th>
                  </tr>
                </thead>
                <tbody>
                  {quarantined.map((evt) => {
                    const state = replayState[evt.event_id];
                    return (
                      <tr
                        key={evt.event_id}
                        className="border-b border-rally-line/60"
                        data-testid={`quarantined-row-${evt.event_id}`}
                      >
                        <Td>
                          <span className="font-mono text-xs text-rally-muted">
                            {truncate(evt.event_id)}
                          </span>
                        </Td>
                        <Td>
                          <Chip variant="manual" label={evt.event_type} />
                        </Td>
                        <Td>
                          <span className="text-xs text-rally-muted">
                            {evt.error_message ?? "—"}
                          </span>
                        </Td>
                        <Td>
                          {state ? (
                            <span className="text-xs text-rally-muted">{state}</span>
                          ) : (
                            <Button
                              variant="secondary"
                              size="sm"
                              onClick={() => replayMutation.mutate(evt.event_id)}
                              disabled={replayMutation.isPending}
                              data-testid={`replay-${evt.event_id}`}
                            >
                              Replay
                            </Button>
                          )}
                        </Td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </Section>

      <AttemptsDialog row={attemptsInvoice} onClose={() => setAttemptsInvoice(null)} />
    </div>
  );
}

function AttemptsDialog({
  row,
  onClose,
}: {
  row: FailedPaymentRow | null;
  onClose: () => void;
}) {
  const open = row !== null;
  const attemptsQuery = useQuery({
    queryKey: queryKeys.admin.invoiceAttempts(row?.invoice_id ?? "none"),
    queryFn: () => fetchInvoiceAttempts(row!.invoice_id),
    enabled: open,
  });
  const attempts = attemptsQuery.data?.attempts ?? [];

  return (
    <Dialog.Root open={open} onOpenChange={(v) => !v && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-rally-ink/40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 max-h-[90vh] w-full max-w-lg -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-xl bg-white p-6 shadow-xl focus:outline-none">
          <Overline>Invoice detail</Overline>
          <Dialog.Title className="mt-1 font-display text-xl font-semibold tracking-[-0.01em]">
            Payment Attempts
          </Dialog.Title>
          <Dialog.Description className="mt-1 mb-4 text-sm text-rally-muted">
            {row ? `${row.invoice_id} · ${row.parent_name ?? row.parent_id}` : ""}
          </Dialog.Description>

          {attemptsQuery.isLoading ? (
            <TableSkeleton />
          ) : attempts.length === 0 ? (
            <p className="text-sm text-rally-muted">No payment attempts recorded for this invoice.</p>
          ) : (
            <ol className="space-y-3" data-testid="attempts-timeline">
              {attempts.map((a: BillingPaymentAttempt) => {
                const chip = attemptChip(a.status);
                return (
                  <li key={a.attempt_id} className="flex gap-3 text-sm">
                    <span
                      className="mt-1.5 h-2 w-2 flex-shrink-0 rounded-full"
                      style={{
                        background:
                          a.status === "succeeded"
                            ? "#16a34a"
                            : a.status === "requires_action"
                              ? "#d97706"
                              : "#dc2626",
                      }}
                    />
                    <div className="flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-rally-muted">{formatTimestamp(a.created_at)}</span>
                        <Chip variant={chip.variant} label={chip.label} />
                      </div>
                      <div className="mt-0.5 font-mono text-xs text-rally-muted">
                        {a.stripe_payment_intent_id ? truncate(a.stripe_payment_intent_id) : "—"} ·{" "}
                        {formatCents(a.amount_cents)}
                      </div>
                      {a.failure_message && (
                        <div className="mt-0.5 text-xs text-red-600">{a.failure_message}</div>
                      )}
                    </div>
                  </li>
                );
              })}
            </ol>
          )}

          <div className="flex justify-end pt-4">
            <Button variant="secondary" size="sm" onClick={onClose}>
              Close
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function Metric({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <Card p={20}>
      <Overline>{label}</Overline>
      <div className="mt-1.5">
        <BigNum size={28}>
          <span style={accent && value !== "0" ? { color: accent } : undefined}>{value}</span>
        </BigNum>
      </div>
    </Card>
  );
}

function Section({
  title,
  hint,
  badge,
  children,
}: {
  title: string;
  hint?: string;
  badge?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Overline>{title}</Overline>
          {badge && (
            <span className="rounded-full bg-red-50 px-2 py-0.5 text-xs text-red-700">{badge}</span>
          )}
        </div>
        {hint && <span className="text-xs text-rally-muted">{hint}</span>}
      </div>
      {children}
    </section>
  );
}

function Alert({ tone, children }: { tone: "green" | "red"; children: React.ReactNode }) {
  const cls = tone === "green" ? "bg-green-50 text-green-800" : "bg-red-50 text-red-700";
  return <p className={`rounded-md p-3 text-sm ${cls}`}>{children}</p>;
}

function Th({ children, align = "left" }: { children: React.ReactNode; align?: "left" | "right" }) {
  return (
    <th
      className={`px-4 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted ${
        align === "right" ? "text-right" : "text-left"
      }`}
    >
      {children}
    </th>
  );
}

function Td({ children, align = "left" }: { children: React.ReactNode; align?: "left" | "right" }) {
  return (
    <td className={`px-4 py-3 ${align === "right" ? "text-right tabular-nums" : "text-left"}`}>
      {children}
    </td>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="p-8 text-center text-sm text-rally-subtle">{children}</p>;
}

function TableSkeleton() {
  return (
    <div className="space-y-2 p-4">
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-12 animate-pulse rounded-xl bg-rally-line/40" />
      ))}
    </div>
  );
}
