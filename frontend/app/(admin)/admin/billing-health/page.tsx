"use client";

/**
 * Admin Billing Health — the page you open when *Stripe* is the problem.
 *
 * Spec: `docs/superpowers/specs/2026-09-07-billing-health-trim-design.md`.
 *
 * Four things and nothing else: can parents pay (plus the one health verdict),
 * quarantined webhooks with replay, reconciliation (runs, "Reconcile now", the
 * lookup by Stripe id, and the autopay switch-off failures), and linking a
 * Stripe charge to an invoice.
 *
 * Removed by the trim: open failed payments with Retry, the attempts dialog,
 * the dunning ladder and the legacy match queue. The Payments Failed-autopay
 * bucket and the Family billing page own family payment behaviour; keeping a
 * third Retry here meant three places to check and two ways to charge a card.
 *
 * The page computes no verdict of its own: `health` arrives from the backend.
 */

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import {
  confirmLegacyMatch,
  fetchConnectReadiness,
  fetchReconciliationRuns,
  listBillingWebhookEvents,
  replayWebhookEvent,
  triggerReconciliation,
  type AutopayDisableFailures,
  type ConnectReadiness,
  type ReconciliationRun,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { formatCents, parseDollarsToCents } from "@/lib/money";
import { healthPillTone, truncationLine } from "@/lib/billing-health";

import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import { Field } from "@/components/ds/dialog-chrome";
import { BigNum, Overline } from "@/components/ds/typography";

import { ReconciliationLookupPanel } from "./ReconciliationLookupPanel";

/** How many quarantined events the list route returns; the tile shows the true count. */
const WEBHOOK_LIST_LIMIT = 50;

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

function runStatusDot(run: ReconciliationRun): string {
  if (run.quarantined > 0 || run.failed > 0) return "#dc2626"; // red
  if (run.repaired > 0) return "#d97706"; // amber
  return "#16a34a"; // green
}

export default function BillingHealthPage() {
  const queryClient = useQueryClient();
  const [replayState, setReplayState] = useState<Record<string, string>>({});

  const readinessQuery = useQuery({
    queryKey: queryKeys.admin.connectReadiness(),
    queryFn: () => fetchConnectReadiness(),
    refetchInterval: 30_000,
  });
  const runsQuery = useQuery({
    queryKey: queryKeys.admin.reconciliationRuns(),
    queryFn: () => fetchReconciliationRuns(),
    refetchInterval: 30_000,
  });
  const quarantinedQuery = useQuery({
    queryKey: queryKeys.admin.quarantinedEvents(),
    queryFn: () => listBillingWebhookEvents({ status: "quarantined", limit: WEBHOOK_LIST_LIMIT }),
  });

  const readiness = readinessQuery.data;
  const runs = runsQuery.data?.runs ?? [];
  const quarantined = quarantinedQuery.data?.events ?? [];
  const latestRun = runs[0];

  const invalidateAll = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.admin.reconciliationRuns() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.admin.quarantinedEvents() });
    // Replaying a webhook or reconciling changes the verdict, so refresh it too.
    void queryClient.invalidateQueries({ queryKey: queryKeys.admin.connectReadiness() });
  };

  const reconcileMutation = useMutation({
    mutationFn: () => triggerReconciliation(),
    onSuccess: invalidateAll,
  });

  const replayMutation = useMutation({
    mutationFn: (eventId: string) => replayWebhookEvent(eventId),
    onSuccess: (_result, eventId) => {
      setReplayState((prev) => ({ ...prev, [eventId]: "Replayed — processing" }));
      invalidateAll();
    },
    onError: (err: Error, eventId) => {
      setReplayState((prev) => ({ ...prev, [eventId]: err.message ?? "Replay failed" }));
    },
  });

  // Readiness failing is the one fatal error: without it there is no verdict,
  // so show a retry panel rather than a misleading green pill (§7).
  if (readinessQuery.isError) {
    return (
      <div className="space-y-4 p-4 sm:p-6" data-testid="billing-health-page">
        <h1 className="font-display text-2xl font-semibold tracking-[-0.01em]">Billing Health</h1>
        <Card p={20}>
          <div data-testid="billing-health-fatal" className="space-y-3">
            <p className="rounded-md bg-red-50 p-3 text-sm text-red-700">
              {(readinessQuery.error as Error)?.message ??
                "Could not check whether parents can pay."}{" "}
              Nothing else on this page is meaningful until this check succeeds.
            </p>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => void readinessQuery.refetch()}
              data-testid="retry-readiness"
            >
              Try again
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  const health = readiness?.health;
  const pill = healthPillTone(health?.state);
  const truncationNotice = truncationLine(
    quarantined.length,
    readiness?.webhook_events.quarantined ?? 0,
  );

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
              readinessQuery.isLoading ? "bg-neutral-100 text-neutral-600" : pill.className
            }`}
            data-testid="billing-health-status"
            data-state={health?.state ?? (readinessQuery.isLoading ? "loading" : "unknown")}
            data-tone={readinessQuery.isLoading ? "neutral" : pill.tone}
          >
            ● {readinessQuery.isLoading ? "Checking…" : (health?.headline ?? "Health unknown")}
          </span>
          <Button
            variant="primary"
            size="sm"
            onClick={() => reconcileMutation.mutate()}
            disabled={reconcileMutation.isPending}
            data-testid="run-reconciliation"
          >
            {reconcileMutation.isPending ? "Running…" : "Reconcile now"}
          </Button>
        </div>
      </div>

      {reconcileMutation.isError && (
        <Alert tone="red">
          {(reconcileMutation.error as Error)?.message ?? "Reconciliation failed."}
        </Alert>
      )}

      {health && health.reasons.length > 0 && (
        <ul className="space-y-1 text-sm text-rally-muted" data-testid="health-reasons">
          {health.reasons.map((reason) => (
            <li key={reason.code} data-reason={reason.code}>
              {reason.detail}
            </li>
          ))}
        </ul>
      )}

      {/* Three tiles, all fed by the readiness response (§4.3) */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Metric
          label="Connect state"
          value={readiness?.connected_account.ready_for_charges ? "Ready" : "Not ready"}
          hint={
            readiness?.funds_route_to_academy
              ? "Funds route to the academy"
              : readiness?.payments_possible
                ? "Funds land on the platform account"
                : "No parent can pay"
          }
          accent={readiness?.connected_account.ready_for_charges ? undefined : "#dc2626"}
        />
        <Metric
          label="Quarantined events"
          value={String(readiness?.webhook_events.quarantined ?? 0)}
          hint={`${readiness?.webhook_events.failed ?? 0} failed`}
          accent="#d97706"
        />
        <Metric
          label="Last reconciliation"
          value={relativeFromNow(latestRun?.finished_at ?? null)}
          hint={
            latestRun
              ? `${latestRun.repaired} repaired · ${latestRun.failed} failed`
              : "No run recorded"
          }
          accent={latestRun && latestRun.failed > 0 ? "#dc2626" : undefined}
        />
      </div>

      <PaymentReadinessCard query={readinessQuery} />

      {/* Webhooks */}
      <Section
        title="Webhooks"
        hint="Quarantined events Stripe sent that we never applied"
        badge={quarantined.length > 0 ? `${quarantined.length} pending` : undefined}
      >
        <Card p={0}>
          {quarantinedQuery.isLoading ? (
            <TableSkeleton />
          ) : quarantinedQuery.isError ? (
            <Alert tone="red">
              {(quarantinedQuery.error as Error)?.message ?? "Could not load quarantined events."}
            </Alert>
          ) : quarantined.length === 0 ? (
            <Alert tone="green">No quarantined webhook events.</Alert>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table
                  className="w-full min-w-[720px] text-sm"
                  data-testid="quarantined-events-table"
                >
                  <thead>
                    <tr className="border-b border-rally-line text-left">
                      <Th>Event ID</Th>
                      <Th>Type</Th>
                      <Th>Reason quarantined</Th>
                      <Th>
                        <span className="sr-only">Action</span>
                      </Th>
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
              {truncationNotice && (
                <p className="px-4 py-3 text-xs text-rally-muted" data-testid="webhook-truncation">
                  {truncationNotice}
                </p>
              )}
            </>
          )}
        </Card>
      </Section>

      {/* Reconciliation */}
      <Section title="Reconciliation" hint="Runs every 10 min · showing last 10">
        <Card p={0}>
          {runsQuery.isLoading ? (
            <TableSkeleton />
          ) : runsQuery.isError ? (
            <Alert tone="red">
              {(runsQuery.error as Error)?.message ?? "Could not load reconciliation runs."}
            </Alert>
          ) : runs.length === 0 ? (
            <Empty>No runs recorded yet. The scheduler runs every 10 minutes.</Empty>
          ) : (
            <div className="overflow-x-auto">
              <table
                className="w-full min-w-[720px] text-sm"
                data-testid="reconciliation-runs-table"
              >
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

        <ReconciliationLookupPanel />

        <AutopaySwitchOffLine failures={readiness?.autopay_disable_failures} />
      </Section>

      {/* Link a Stripe charge */}
      <Section
        title="Link a Stripe charge"
        hint="For a charge that only exists in Stripe — a migrated invoice, or one the webhook never reached"
      >
        <LinkChargeForm onLinked={invalidateAll} />
      </Section>
    </div>
  );
}

/**
 * "Autopay switch-off failed for {n} invoices" (§4.4).
 *
 * When the dunning ladder runs out the worker switches autopay off, and that
 * Stripe call can itself fail — meaning the worker believes autopay is off
 * while the card may still be attached. Nothing else in the product shows it.
 * No action: the worker retries on its next pass.
 */
function AutopaySwitchOffLine({ failures }: { failures?: AutopayDisableFailures }) {
  if (!failures || failures.count === 0) return null;
  return (
    <Card p={16}>
      <div data-testid="autopay-switch-off-failures" className="space-y-2 text-sm">
        <p className="font-medium text-red-700">
          Autopay switch-off failed for {failures.count}{" "}
          {failures.count === 1 ? "invoice" : "invoices"}
        </p>
        <p className="text-xs text-rally-muted">
          The worker believes autopay is off for these; the card may still be attached in Stripe.
          It retries on its next pass.
        </p>
        <ul className="space-y-1">
          {failures.rows.map((row) => (
            <li key={row.invoice_id} className="flex flex-wrap items-baseline gap-2">
              <Link
                href={`/admin/families/${encodeURIComponent(row.parent_id)}`}
                className="font-mono text-xs underline"
                data-testid={`switch-off-${row.invoice_id}`}
              >
                {row.invoice_id}
              </Link>
              <span className="text-xs text-rally-muted">{row.error ?? "no error recorded"}</span>
              <span className="text-xs text-rally-subtle">{formatTimestamp(row.failed_at)}</span>
            </li>
          ))}
        </ul>
        {failures.truncated && (
          <p className="text-xs text-rally-subtle">
            Showing the {failures.rows.length} most recent of {failures.count}.
          </p>
        )}
      </div>
    </Card>
  );
}

/**
 * Link a Stripe charge to an invoice — the surviving half of legacy match.
 *
 * The endpoint is idempotent on the (charge, invoice) pair, so a double submit
 * is safe, and it refuses an invoice that is not payable or an amount above
 * the balance; both render inline. The confirmation names the invoice and the
 * amount before anything is posted.
 */
function LinkChargeForm({ onLinked }: { onLinked: () => void }) {
  const [invoiceId, setInvoiceId] = useState("");
  const [chargeId, setChargeId] = useState("");
  const [amount, setAmount] = useState("");
  const [paymentIntentId, setPaymentIntentId] = useState("");
  const [paidAt, setPaidAt] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  const amountCents = parseDollarsToCents(amount);
  const ready = Boolean(invoiceId.trim() && chargeId.trim()) && amountCents > 0;

  const mutation = useMutation({
    mutationFn: () =>
      confirmLegacyMatch({
        invoice_id: invoiceId.trim(),
        stripe_charge_id: chargeId.trim(),
        amount_cents: amountCents,
        stripe_payment_intent_id: paymentIntentId.trim() || null,
        paid_at: paidAt ? new Date(paidAt).toISOString() : null,
      }),
    onSuccess: () => {
      setError(null);
      setConfirming(false);
      onLinked();
    },
    onError: (err: Error) => {
      setError(err.message ?? "Could not link that charge.");
      setConfirming(false);
    },
  });

  return (
    <Card p={16}>
      <form
        data-testid="link-charge-form"
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (!ready) {
            setError("An invoice ID, a charge ID and a positive amount are required.");
            return;
          }
          setError(null);
          setConfirming(true);
        }}
      >
        <div className="grid gap-3 lg:grid-cols-3">
          <Field label="Invoice ID">
            <input
              value={invoiceId}
              onChange={(e) => setInvoiceId(e.target.value)}
              className={inputClass}
              placeholder="inv-..."
              data-testid="link-invoice-id"
            />
          </Field>
          <Field label="Stripe charge ID">
            <input
              value={chargeId}
              onChange={(e) => setChargeId(e.target.value)}
              className={inputClass}
              placeholder="ch_..."
              data-testid="link-charge-id"
            />
          </Field>
          <Field label="Amount">
            <input
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className={inputClass}
              placeholder="70.00"
              inputMode="decimal"
              data-testid="link-amount"
            />
          </Field>
          <Field label="PaymentIntent ID (optional)">
            <input
              value={paymentIntentId}
              onChange={(e) => setPaymentIntentId(e.target.value)}
              className={inputClass}
              placeholder="pi_..."
              data-testid="link-payment-intent-id"
            />
          </Field>
          <Field label="Paid at (optional)">
            <input
              type="date"
              value={paidAt}
              onChange={(e) => setPaidAt(e.target.value)}
              className={inputClass}
              data-testid="link-paid-at"
            />
          </Field>
        </div>
        <div className="flex items-center gap-3">
          <Button variant="secondary" size="sm" type="submit" data-testid="link-charge-submit">
            Review
          </Button>
          {mutation.isSuccess && !confirming && (
            <span className="text-sm text-green-700" data-testid="link-charge-success">
              Linked. Invoice {mutation.data?.invoice_id} is now {mutation.data?.invoice_status}.
            </span>
          )}
        </div>
      </form>

      {error && (
        <p className="mt-3 rounded-md bg-red-50 p-3 text-sm text-red-700" data-testid="link-error">
          {error}
        </p>
      )}

      {confirming && (
        <div
          className="mt-3 space-y-3 rounded-md border border-rally-line bg-rally-paper/50 p-3 text-sm"
          data-testid="link-charge-confirm"
        >
          <p>
            Record {formatCents(amountCents)} against invoice{" "}
            <span className="font-mono">{invoiceId.trim()}</span> from Stripe charge{" "}
            <span className="font-mono">{chargeId.trim()}</span>?
          </p>
          <p className="text-xs text-rally-muted">
            This records a back-dated payment. Re-submitting the same charge and invoice is safe —
            it will not pay the invoice twice.
          </p>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setConfirming(false)}
              disabled={mutation.isPending}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={() => mutation.mutate()}
              disabled={mutation.isPending}
              data-testid="link-charge-confirm-submit"
            >
              {mutation.isPending ? "Recording…" : "Link the charge"}
            </Button>
          </div>
        </div>
      )}
    </Card>
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

/**
 * Can this academy physically take a payment, and where does the money land?
 * (issue #432). Takes its tone from the backend verdict rather than deriving
 * one of its own.
 */
function PaymentReadinessCard({ query }: { query: UseQueryResult<ConnectReadiness> }) {
  if (query.isLoading) {
    return (
      <Card p={20}>
        <div className="h-5 w-48 animate-pulse rounded bg-rally-line" />
      </Card>
    );
  }
  if (!query.data) return null;

  const data = query.data;
  const account = data.connected_account;
  const tone = !data.payments_possible ? "red" : data.funds_route_to_academy ? "green" : "amber";

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
            value={`${data.webhook_events.quarantined} quarantined · ${data.webhook_events.failed} failed`}
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

function Metric({
  label,
  value,
  hint,
  accent,
}: {
  label: string;
  value: string;
  hint?: string;
  accent?: string;
}) {
  return (
    <Card p={20}>
      <Overline>{label}</Overline>
      <div className="mt-1.5">
        <BigNum size={28}>
          <span style={accent && value !== "0" ? { color: accent } : undefined}>{value}</span>
        </BigNum>
      </div>
      {hint && <p className="mt-1 text-xs text-rally-muted">{hint}</p>}
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

const inputClass =
  "w-full rounded-md border border-rally-line bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600/30";
