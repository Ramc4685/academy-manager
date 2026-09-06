"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useIsOwner } from "@/components/admin/owner-context";
import { Button, Card, Skeleton } from "@/components/ds";
import {
  applyAdminInvoiceAdjustment,
  chargeAdminInvoiceAutopay,
  enableBillingSetupAutopay,
  fetchInvoiceAudit,
  inviteBillingSetupParent,
  refundAdminInvoice,
  sendAdminInvoice,
  voidAdminInvoice,
} from "@/lib/api/admin";
import {
  fetchAdminFamilyBilling,
  pauseFamilyAutopay,
  type FamilyInvoice,
  type InvoiceAction,
} from "@/lib/api/admin-families";
import { formatCents } from "@/lib/money";
import { queryKeys } from "@/lib/query/keys";

import { RecordPaymentDialog } from "../../payments/buckets/RecordPaymentDialog";
import { FamilyHeader } from "./FamilyHeader";
import { FixSomethingPanel } from "./FixSomethingPanel";
import { InvoicesPanel } from "./InvoicesPanel";
import { StudentsPanel } from "./StudentsPanel";
import { TimelinePanel } from "./TimelinePanel";
import { ReasonDialog, type ReasonDialogKind, type ReasonDialogResult } from "./family-dialogs";
import { mintRequestId, periodLabel } from "./family-view";

type DialogState = { kind: ReasonDialogKind; invoiceId: string | null };

function invoiceSubject(inv: FamilyInvoice, amountCents: number): string {
  return `${periodLabel(inv.period)}${inv.student_name ? ` · ${inv.student_name}` : ""} · ${formatCents(amountCents)}`;
}

export default function FamilyBillingPage() {
  const params = useParams<{ parentId: string }>();
  const parentId = params.parentId;
  const queryClient = useQueryClient();
  const isOwner = useIsOwner();
  const [dialog, setDialog] = useState<DialogState | null>(null);
  // `false` = closed; `null` = open with no preselected invoice; string = preselected.
  const [recordFor, setRecordFor] = useState<string | null | false>(false);
  const [recordKey, setRecordKey] = useState(0);
  const [audit, setAudit] = useState<{ invoice: FamilyInvoice; entries: unknown[] } | null>(
    null,
  );
  const [toast, setToast] = useState<string | null>(null);

  const query = useQuery({
    queryKey: queryKeys.admin.familyBilling(parentId),
    queryFn: () => fetchAdminFamilyBilling(parentId),
  });

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.admin.familyBilling(parentId) });
    await queryClient.invalidateQueries({ queryKey: queryKeys.admin.collectionsAll() });
  };

  const simple = useMutation({
    mutationFn: async (fn: () => Promise<unknown>) => fn(),
    onSuccess: () => void refresh(),
    onError: (err: Error) => setToast(err.message),
  });

  const view = query.data;
  const invoiceById = new Map((view?.invoices ?? []).map((inv) => [inv.invoice_id, inv]));
  const target = dialog?.invoiceId ? (invoiceById.get(dialog.invoiceId) ?? null) : null;

  const submitReason = async (r: ReasonDialogResult) => {
    if (!dialog) return;
    const invoiceId = dialog.invoiceId;
    switch (dialog.kind) {
      case "void":
        if (!invoiceId) return;
        await voidAdminInvoice(invoiceId, { reason: r.reason });
        break;
      case "refund":
        if (!invoiceId) return;
        await refundAdminInvoice(invoiceId, { amount_cents: r.amount_cents, reason: r.reason });
        break;
      case "discount_once":
        if (!invoiceId) return;
        await applyAdminInvoiceAdjustment(invoiceId, {
          description: r.description ?? "Discount",
          amount_cents: -(r.amount_cents ?? 0),
          reason: r.reason,
        });
        break;
      case "charge_card":
        if (!invoiceId) return;
        await chargeAdminInvoiceAutopay(invoiceId, r.reason);
        break;
      case "send_invoice":
        if (!invoiceId) return;
        await sendAdminInvoice(invoiceId);
        break;
      case "autopay_off":
        await pauseFamilyAutopay(parentId, { reason: r.reason, request_id: mintRequestId() });
        break;
    }
    await refresh();
  };

  const openRecordPayment = (invoiceId: string | null) => {
    setRecordKey((k) => k + 1);
    setRecordFor(invoiceId);
  };

  const onInvoiceAction = (action: InvoiceAction, inv: FamilyInvoice) => {
    if (action === "record_payment") openRecordPayment(inv.invoice_id);
    else if (action === "send") setDialog({ kind: "send_invoice", invoiceId: inv.invoice_id });
    else setDialog({ kind: action, invoiceId: inv.invoice_id });
  };

  if (query.isLoading) {
    return (
      <section data-testid="admin-family-billing" className="space-y-4">
        <Card p={20}>
          <Skeleton lines={3} />
        </Card>
        <Card p={20}>
          <Skeleton lines={4} />
        </Card>
        <Card p={20}>
          <Skeleton lines={6} />
        </Card>
      </section>
    );
  }
  if (query.isError || !view) {
    return (
      <section data-testid="admin-family-billing" className="space-y-4">
        <Card p={20}>
          <p className="text-sm text-rally-ink" data-testid="family-error">
            Could not load this family. {(query.error as Error | null)?.message ?? ""}
          </p>
          <Button
            size="sm"
            variant="secondary"
            className="mt-2"
            data-testid="family-retry"
            onClick={() => void query.refetch()}
          >
            Retry
          </Button>
        </Card>
      </section>
    );
  }

  const owingInvoices = view.invoices
    .filter((i) => i.actions.includes("record_payment"))
    .map((i) => ({
      invoice_id: i.invoice_id,
      label: invoiceSubject(i, i.balance_due_cents),
      balance_due_cents: i.balance_due_cents,
    }));
  const subject = target
    ? invoiceSubject(target, target.total_cents)
    : `${view.parent.name ?? "This family"} · ${view.header.autopay.active_count} enrollments on autopay`;
  const maxAmount =
    target && dialog?.kind === "refund"
      ? target.allocations
          .filter((a) => a.stripe_payment_intent_id)
          .reduce((s, a) => s + a.amount_cents, 0)
      : target && dialog?.kind === "discount_once"
        ? target.balance_due_cents
        : null;

  return (
    <section data-testid="admin-family-billing" className="space-y-4">
      {toast && (
        <div
          role="status"
          className="rounded-lg border border-rally-line bg-white px-3 py-2 text-sm text-rally-ink"
          data-testid="family-toast"
        >
          {toast}{" "}
          <button
            type="button"
            className="ml-2 text-rally-muted"
            aria-label="Dismiss"
            onClick={() => setToast(null)}
          >
            ×
          </button>
        </div>
      )}
      <FamilyHeader
        view={view}
        busy={simple.isPending}
        onToggleAutopay={(turnOn) => {
          if (turnOn) simple.mutate(() => enableBillingSetupAutopay(parentId, mintRequestId()));
          else setDialog({ kind: "autopay_off", invoiceId: null });
        }}
        onSendInvite={() =>
          simple.mutate(async () => {
            const r = await inviteBillingSetupParent(parentId);
            setToast(r.ok ? "Invite sent." : `Invite failed: ${r.failed_reason ?? "unknown"}`);
          })
        }
        onSendInvoice={() => {
          const first = view.invoices.find((i) => i.actions.includes("send"));
          if (first) setDialog({ kind: "send_invoice", invoiceId: first.invoice_id });
        }}
        onRecordPayment={() => openRecordPayment(null)}
      />
      <StudentsPanel students={view.students} isOwner={isOwner} />
      <InvoicesPanel
        invoices={view.invoices}
        busy={simple.isPending}
        onAction={onInvoiceAction}
        onFullAudit={(inv) =>
          simple.mutate(async () => {
            const r = await fetchInvoiceAudit(inv.invoice_id);
            setAudit({ invoice: inv, entries: r.entries });
          })
        }
      />
      <TimelinePanel timeline={view.timeline} warnings={view.warnings} />
      <FixSomethingPanel
        invoices={view.invoices}
        isOwner={isOwner}
        onPick={(kind, invoiceId) => setDialog({ kind, invoiceId })}
      />

      {dialog && (
        <ReasonDialog
          kind={dialog.kind}
          open
          subject={subject}
          maxAmountCents={maxAmount}
          onClose={() => setDialog(null)}
          onSubmit={submitReason}
        />
      )}
      <RecordPaymentDialog
        key={recordKey}
        open={recordFor !== false}
        invoices={owingInvoices}
        initialInvoiceId={typeof recordFor === "string" ? recordFor : undefined}
        onClose={() => setRecordFor(false)}
        onSaved={() => {
          setRecordFor(false);
          void refresh();
        }}
      />
      {audit && (
        <Card p={20} data-testid="invoice-audit-drawer">
          <div className="flex items-center justify-between">
            <span className="font-semibold">Full audit · {periodLabel(audit.invoice.period)}</span>
            <Button size="sm" variant="secondary" onClick={() => setAudit(null)}>
              Close
            </Button>
          </div>
          <pre className="mt-2 max-h-80 overflow-auto rounded bg-rally-paper p-2 text-xs">
            {JSON.stringify(audit.entries, null, 2)}
          </pre>
        </Card>
      )}
    </section>
  );
}
