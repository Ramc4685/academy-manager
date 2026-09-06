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
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";

import {
  chargeAdminInvoiceAutopay,
  confirmLegacyMatch,
  fetchConnectReadiness,
  fetchDunningFailures,
  fetchFailedPaymentAttempts,
  fetchInvoiceAttempts,
  fetchLegacyMatchQueue,
  fetchReconciliationRuns,
  listBillingWebhookEvents,
  replayWebhookEvent,
  triggerReconciliation,
  type BillingPaymentAttempt,
  type ConnectedAccountReadiness,
  type ConnectReadiness,
  type DunningRow,
  type FailedPaymentRow,
  type LegacyMatchCandidate,
  type LegacyMatchRow,
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

const ACTIVE_DUNNING_STATUSES = new Set(["active", "processing", "dunned"]);

function dunningChip(status: string): { variant: ChipVariant; label: string } {
  if (status === "resolved") return { variant: "paid", label: "RESOLVED" };
  if (status === "dunned") return { variant: "failed", label: "DUNNED" };
  if (status === "processing") return { variant: "pending", label: "PROCESSING" };
  if (status === "suppressed") return { variant: "manual", label: "SUPPRESSED" };
  return { variant: "overdue", label: status.replace(/_/g, " ").toUpperCase() };
}

function dunningDisableText(row: DunningRow): string {
  if (row.autopay_disable_status === "failed") {
    return `Disable failed: ${row.autopay_disable_error ?? "needs retry"}`;
  }
  if (row.autopay_disable_status === "succeeded") {
    return `Disabled ${formatTimestamp(row.autopay_disabled_at)}`;
  }
  if (row.status === "dunned") return "Disable pending";
  return "—";
}

export default function BillingHealthPage() {
  const queryClient = useQueryClient();
  const [attemptsInvoice, setAttemptsInvoice] = useState<FailedPaymentRow | null>(null);
  const [retryResult, setRetryResult] = useState<Record<string, string>>({});
  const [replayState, setReplayState] = useState<Record<string, string>>({});
  const [matchTarget, setMatchTarget] = useState<{
    row: LegacyMatchRow;
    candidate: LegacyMatchCandidate;
  } | null>(null);

  const runsQuery = useQuery({
    queryKey: queryKeys.admin.reconciliationRuns(),
    queryFn: () => fetchReconciliationRuns(),
    refetchInterval: 30_000,
  });
  const failedQuery = useQuery({
    queryKey: queryKeys.admin.failedAttempts(),
    queryFn: () => fetchFailedPaymentAttempts(),
  });
  const dunningQuery = useQuery({
    queryKey: queryKeys.admin.dunningFailures(),
    queryFn: () => fetchDunningFailures(),
  });
  const quarantinedQuery = useQuery({
    queryKey: queryKeys.admin.quarantinedEvents(),
    queryFn: () => listBillingWebhookEvents({ status: "quarantined", limit: 50 }),
  });
  const legacyQuery = useQuery({
    queryKey: queryKeys.admin.legacyMatchQueue(),
    queryFn: () => fetchLegacyMatchQueue(),
  });
  const readinessQuery = useQuery({
    queryKey: queryKeys.admin.connectReadiness(),
    queryFn: () => fetchConnectReadiness(),
    refetchInterval: 30_000,
  });

  const webhookCounts = readinessQuery.data?.webhook_events;
  const runs = runsQuery.data?.runs ?? [];
  const failedRows = failedQuery.data?.rows ?? [];
  const quarantined = quarantinedQuery.data?.events ?? [];
  const legacyRows = legacyQuery.data?.rows ?? [];
  const latestRun = runs[0];
  const dunningRows = dunningQuery.data?.rows ?? [];
  // The backend endpoint (MongoDunningStateRepository.list_admin_rows) returns
  // only "dunned" / "active" (attempt_count > 0) / "processing" states, but
  // filter defensively so resolved/suppressed rows never trip the red metric.
  const activeDunningRows = dunningRows.filter((row) =>
    ACTIVE_DUNNING_STATUSES.has(row.status),
  );

  const invalidateAll = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.admin.reconciliationRuns() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.admin.failedAttempts() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.admin.dunningFailures() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.admin.quarantinedEvents() });
    // Replaying a webhook changes its status, so the backlog counts move too.
    void queryClient.invalidateQueries({ queryKey: queryKeys.admin.connectReadiness() });
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

  const confirmMatchMutation = useMutation({
    mutationFn: () => {
      const { row, candidate } = matchTarget!;
      return confirmLegacyMatch({
        invoice_id: row.invoice_id,
        stripe_charge_id: candidate.stripe_charge_id,
        amount_cents: row.balance_due_cents,
        stripe_payment_intent_id: candidate.stripe_payment_intent_id,
        paid_at: candidate.created_at,
      });
    },
    onSuccess: () => {
      setMatchTarget(null);
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.legacyMatchQueue() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.failedAttempts() });
    },
  });

  const healthy =
    failedRows.length === 0 && activeDunningRows.length === 0 && quarantined.length === 0;
  // "Healthy" is only a meaningful claim once at least one reconciliation run
  // has happened; before that, the system state is unknown, not healthy.
  const hasRunData = runs.length > 0;

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
              !healthy
                ? "bg-red-50 text-red-700"
                : hasRunData
                  ? "bg-green-50 text-green-700"
                  : "bg-neutral-100 text-neutral-600"
            }`}
            data-testid="billing-health-status"
          >
            ●{" "}
            {!healthy
              ? "Needs attention"
              : hasRunData
                ? "System healthy"
                : "No reconciliation run yet"}
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

      {/* Can we take money at all? (#432) — first thing on the page, because
          every other number here is moot if the answer is no. */}
      <PaymentReadinessCard query={readinessQuery} />

      {/* Stat cards */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
        <Metric label="Last Run Scanned" value={String(latestRun?.scanned ?? 0)} />
        <Metric label="Repaired" value={String(latestRun?.repaired ?? 0)} accent="#16a34a" />
        <Metric label="Open Failed Payments" value={String(failedRows.length)} accent="#dc2626" />
        <Metric label="Dunning Cases" value={String(activeDunningRows.length)} accent="#dc2626" />
        {/* Real counts, not the length of a 50-capped list: "50 quarantined"
            used to mean anything from 50 to 5,000. */}
        <Metric
          label="Quarantined Events"
          value={String(webhookCounts?.quarantined ?? quarantined.length)}
          accent="#d97706"
        />
        <Metric
          label="Failed Events"
          value={String(webhookCounts?.failed ?? 0)}
          accent="#dc2626"
        />
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
                    <ReconciliationRunRow key={run.run_id} run={run} />
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

      {/* Section 3: Dunning ladder */}
      <Section
        title="Dunning Ladder"
        hint="App-owned retry states and terminal autopay disable status"
        badge={dunningRows.length > 0 ? `${dunningRows.length} need review` : undefined}
      >
        <Card p={0}>
          {dunningQuery.isLoading ? (
            <TableSkeleton />
          ) : dunningRows.length === 0 ? (
            <Alert tone="green">No active or terminal dunning cases.</Alert>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[920px] text-sm" data-testid="dunning-table">
                <thead>
                  <tr className="border-b border-rally-line text-left">
                    <Th>Parent · Invoice</Th>
                    <Th>Status</Th>
                    <Th align="right">Balance</Th>
                    <Th>Attempts</Th>
                    <Th>Next / terminal</Th>
                    <Th>Autopay disable</Th>
                  </tr>
                </thead>
                <tbody>
                  {dunningRows.map((row) => {
                    const chip = dunningChip(row.status);
                    return (
                      <tr
                        key={row.invoice_id}
                        className="border-b border-rally-line/60"
                        data-testid={`dunning-row-${row.invoice_id}`}
                      >
                        <Td>
                          <div className="font-medium text-rally-ink">
                            {row.parent_name ?? row.parent_id}
                          </div>
                          <div className="text-xs text-rally-muted">
                            {row.invoice_id} · {row.period}
                          </div>
                        </Td>
                        <Td>
                          <Chip variant={chip.variant} label={chip.label} />
                          {row.last_failure_code && (
                            <div className="mt-1 text-xs text-rally-muted">
                              {row.last_failure_code}
                            </div>
                          )}
                        </Td>
                        <Td align="right">{formatCents(row.balance_due_cents)}</Td>
                        <Td>{row.attempt_count}</Td>
                        <Td>
                          <div>
                            {row.next_attempt_at
                              ? `Next: ${formatTimestamp(row.next_attempt_at)}`
                              : row.terminal_at
                                ? `Terminal: ${formatTimestamp(row.terminal_at)}`
                                : "—"}
                          </div>
                          {row.last_attempt_at && (
                            <div className="text-xs text-rally-muted">
                              Last {formatTimestamp(row.last_attempt_at)}
                            </div>
                          )}
                        </Td>
                        <Td>
                          <span
                            className={
                              row.autopay_disable_status === "failed"
                                ? "text-xs font-medium text-red-600"
                                : "text-xs text-rally-muted"
                            }
                          >
                            {dunningDisableText(row)}
                          </span>
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

      {/* Section 4: Quarantined webhook events */}
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

      {/* Section 5: Legacy invoice ↔ Stripe charge review queue (#242 WI-3) */}
      <Section
        title="Legacy Invoice Matches"
        hint="Migrated invoices with no app-linked payment · confirm a charge to settle"
        badge={legacyRows.length > 0 ? `${legacyRows.length} to review` : undefined}
      >
        <Card p={0}>
          {legacyQuery.isLoading ? (
            <TableSkeleton />
          ) : legacyQuery.isError ? (
            <Alert tone="red">
              {(legacyQuery.error as Error)?.message ?? "Could not load the match queue."}
            </Alert>
          ) : legacyRows.length === 0 ? (
            <Alert tone="green">No unmatched legacy invoices.</Alert>
          ) : (
            <div className="divide-y divide-rally-line/60" data-testid="legacy-match-list">
              {legacyRows.map((row) => (
                <LegacyMatchRowView
                  key={row.invoice_id}
                  row={row}
                  onConfirm={(candidate) => setMatchTarget({ row, candidate })}
                />
              ))}
            </div>
          )}
        </Card>
      </Section>

      <AttemptsDialog row={attemptsInvoice} onClose={() => setAttemptsInvoice(null)} />
      <ConfirmMatchDialog
        target={matchTarget}
        pending={confirmMatchMutation.isPending}
        error={confirmMatchMutation.isError ? (confirmMatchMutation.error as Error)?.message : null}
        onConfirm={() => confirmMatchMutation.mutate()}
        onClose={() => {
          if (!confirmMatchMutation.isPending) {
            confirmMatchMutation.reset();
            setMatchTarget(null);
          }
        }}
      />
    </div>
  );
}

function ReconciliationRunRow({ run }: { run: ReconciliationRun }) {
  const errors = Array.isArray(run.errors) ? run.errors : [];
  const notes = Array.isArray(run.notes) ? run.notes : [];
  return (
    <tr className="border-b border-rally-line/60">
      <Td>
        <span style={{ color: runStatusDot(run) }}>● </span>
        {formatTimestamp(run.started_at)}
      </Td>
      <Td align="right">{run.scanned}</Td>
      <Td align="right">{run.repaired}</Td>
      <Td align="right">{run.skipped}</Td>
      <Td align="right">{run.quarantined}</Td>
      <Td>
        <NotesCell errors={errors} notes={notes} />
      </Td>
    </tr>
  );
}

function NotesCell({ errors, notes }: { errors: unknown[]; notes: string[] }) {
  const all = [...errors.map(String), ...notes.map(String)];
  if (all.length === 0) return <span className="text-rally-muted">—</span>;
  const first = all[0];
  if (all.length === 1 && first.length <= 80) {
    return <span className="text-rally-muted">{first}</span>;
  }
  return (
    <details className="text-rally-muted">
      <summary className="cursor-pointer select-none">
        {truncate(first, 80)}
        {all.length > 1 ? ` (+${all.length - 1} more)` : ""}
      </summary>
      <ul className="mt-1 max-w-md space-y-1 whitespace-pre-wrap break-words text-xs">
        {all.map((text, i) => (
          <li key={i}>{text}</li>
        ))}
      </ul>
    </details>
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

function confidenceChip(confidence: string): { variant: ChipVariant; label: string } {
  if (confidence === "high") return { variant: "paid", label: "HIGH MATCH" };
  return { variant: "pending", label: "REVIEW" };
}

function LegacyMatchRowView({
  row,
  onConfirm,
}: {
  row: LegacyMatchRow;
  onConfirm: (candidate: LegacyMatchCandidate) => void;
}) {
  return (
    <div className="p-4" data-testid={`legacy-row-${row.invoice_id}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <div className="font-medium text-rally-ink">{row.parent_name ?? row.parent_id}</div>
          <div className="text-xs text-rally-muted">
            {row.invoice_id} · {row.period} · balance {formatCents(row.balance_due_cents)}
          </div>
        </div>
        <Chip
          variant={row.status === "partially_paid" ? "pending" : "failed"}
          label={row.status.replace(/_/g, " ").toUpperCase()}
        />
      </div>

      {row.candidates.length === 0 ? (
        <p className="mt-3 text-sm text-rally-muted">
          {row.stripe_customer_id
            ? "No matching Stripe charges found for this customer."
            : "No Stripe customer on file for this parent."}
        </p>
      ) : (
        <ul className="mt-3 space-y-2" data-testid={`legacy-candidates-${row.invoice_id}`}>
          {row.candidates.map((candidate) => {
            const chip = confidenceChip(candidate.confidence);
            const exact = candidate.amount_cents === row.balance_due_cents;
            return (
              <li
                key={candidate.stripe_charge_id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-rally-line/60 px-3 py-2"
              >
                <div className="text-sm">
                  <div className="flex items-center gap-2">
                    <span className="font-medium tabular-nums">
                      {formatCents(candidate.amount_cents)}
                    </span>
                    <Chip variant={chip.variant} label={chip.label} />
                    {!exact && (
                      <span className="text-xs text-amber-600">≠ balance</span>
                    )}
                  </div>
                  <div className="mt-0.5 font-mono text-xs text-rally-muted">
                    {truncate(candidate.stripe_charge_id, 22)} · {formatTimestamp(candidate.created_at)}
                  </div>
                </div>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={!exact}
                  onClick={() => onConfirm(candidate)}
                  data-testid={`confirm-${row.invoice_id}-${candidate.stripe_charge_id}`}
                >
                  Confirm match
                </Button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function ConfirmMatchDialog({
  target,
  pending,
  error,
  onConfirm,
  onClose,
}: {
  target: { row: LegacyMatchRow; candidate: LegacyMatchCandidate } | null;
  pending: boolean;
  error: string | null;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const open = target !== null;
  return (
    <Dialog.Root open={open} onOpenChange={(v) => !v && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-rally-ink/40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-xl bg-white p-6 shadow-xl focus:outline-none">
          <Overline>Confirm legacy match</Overline>
          <Dialog.Title className="mt-1 font-display text-xl font-semibold tracking-[-0.01em]">
            Apply this Stripe charge?
          </Dialog.Title>
          <Dialog.Description className="mt-1 mb-4 text-sm text-rally-muted">
            This records a back-dated payment and marks the invoice as paid. It cannot be undone
            from here — verify the charge belongs to this invoice.
          </Dialog.Description>

          {target && (
            <dl className="space-y-2 rounded-lg bg-rally-line/20 p-3 text-sm">
              <Row label="Invoice" value={`${target.row.invoice_id} · ${target.row.period}`} />
              <Row label="Parent" value={target.row.parent_name ?? target.row.parent_id} />
              <Row label="Charge" value={target.candidate.stripe_charge_id} mono />
              <Row label="Amount" value={formatCents(target.candidate.amount_cents)} />
              <Row label="Charged" value={formatTimestamp(target.candidate.created_at)} />
            </dl>
          )}

          {error && <p className="mt-3 rounded-md bg-red-50 p-2 text-sm text-red-700">{error}</p>}

          <div className="flex justify-end gap-2 pt-4">
            <Button variant="secondary" size="sm" onClick={onClose} disabled={pending}>
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={onConfirm}
              disabled={pending}
              data-testid="confirm-match-submit"
            >
              {pending ? "Recording…" : "Confirm & record payment"}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/**
 * Can this academy physically take a payment, and where does the money land?
 * (issue #432)
 *
 * Every parent payment is gated on one condition — an `active` Stripe Connect
 * account with charges enabled — or on the platform-charge fallback being on.
 * Nothing in the admin UI showed either, so an academy could be unable to
 * collect a cent with no signal anywhere.
 */
function PaymentReadinessCard({
  query,
}: {
  query: UseQueryResult<ConnectReadiness>;
}) {
  if (query.isLoading) {
    return (
      <Card p={20}>
        <div className="h-5 w-48 animate-pulse rounded bg-rally-line" />
      </Card>
    );
  }
  if (query.isError || !query.data) {
    return (
      <Alert tone="red">
        {(query.error as Error)?.message ?? "Could not load payment readiness."}
      </Alert>
    );
  }

  const data = query.data;
  // A resolved query still only guarantees the envelope, not every nested
  // object in it, so the two the card dereferences get their own defaults.
  const account: ConnectedAccountReadiness = data.connected_account ?? {
    configured: false,
    status: null,
    charges_enabled: false,
    payouts_enabled: false,
    ready_for_charges: false,
    account_id_masked: null,
  };
  const webhookEvents = data.webhook_events ?? { quarantined: 0, failed: 0 };

  // Three states, in the order the owner cares about them.
  const tone: "green" | "amber" | "red" = !data.payments_possible
    ? "red"
    : data.funds_route_to_academy
      ? "green"
      : "amber";
  // "Ready to take payments", not "payments are working": this card checks the
  // Connect gate, it does not observe a successful charge.
  const headline = !data.payments_possible
    ? "Parents cannot pay right now"
    : data.funds_route_to_academy
      ? "Ready to take payments"
      : "Payments can be taken, but money is landing on the platform account";
  const detail = !data.payments_possible
    ? account.configured
      ? "The academy's Stripe account is connected but not ready to take charges, and the platform fallback is off."
      : "No Stripe account is connected, and the platform fallback is off."
    : data.funds_route_to_academy
      ? "Charges route to the academy's own Stripe account."
      : "The platform charge fallback is on, so charges succeed on the platform account instead of the academy's. Finish Connect onboarding to route funds to the academy.";

  const toneClasses = {
    green: "bg-green-50 text-green-800",
    amber: "bg-amber-50 text-amber-800",
    red: "bg-red-50 text-red-700",
  }[tone];

  return (
    <Card p={20}>
      <div data-testid="payment-readiness" data-tone={tone} className="space-y-3">
        <div className={`rounded-md p-3 text-sm font-medium ${toneClasses}`} role="status">
          <div>{headline}</div>
          <p className="mt-1 font-normal">{detail}</p>
        </div>
        <dl className="grid gap-2 text-sm sm:grid-cols-2">
          <Row
            label="Connected account"
            value={account.account_id_masked ?? "Not connected"}
            mono={Boolean(account.account_id_masked)}
          />
          <Row label="Account status" value={account.status ?? "—"} />
          <Row label="Charges enabled" value={account.charges_enabled ? "Yes" : "No"} />
          <Row label="Payouts enabled" value={account.payouts_enabled ? "Yes" : "No"} />
          <Row
            label="Platform charge fallback"
            value={data.allow_platform_charge_fallback ? "On" : "Off"}
          />
          <Row
            label="Stuck webhook events"
            value={`${webhookEvents.quarantined} quarantined · ${webhookEvents.failed} failed`}
          />
        </dl>
      </div>
    </Card>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-rally-muted">{label}</dt>
      <dd className={`text-right text-rally-ink ${mono ? "font-mono text-xs" : ""}`}>{value}</dd>
    </div>
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
