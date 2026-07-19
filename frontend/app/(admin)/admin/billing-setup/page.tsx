"use client";

/**
 * Admin Billing Setup.
 *
 * Shows which paying parents can be charged today (card on file), which have
 * an account but no saved card, and which have no login account at all — with
 * a context-aware invite action, a one-off "charge now", and "enable autopay"
 * across a parent's eligible children.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  chargeBillingSetupParent,
  enableBillingSetupAutopay,
  fetchBillingSetup,
  inviteBillingSetupParent,
  type BillingSetupRegistrationState,
  type BillingSetupRow,
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

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function stateChip(state: BillingSetupRegistrationState): { variant: ChipVariant; label: string } {
  if (state === "card_on_file") return { variant: "paid", label: "REGISTERED" };
  if (state === "account_no_card") return { variant: "pending", label: "NO CARD" };
  return { variant: "nocharge", label: "NOT INVITED" };
}

const FILTERS: { value: "all" | BillingSetupRegistrationState; label: string }[] = [
  { value: "all", label: "All" },
  { value: "no_account", label: "Not invited" },
  { value: "account_no_card", label: "No card" },
  { value: "card_on_file", label: "Chargeable" },
];

function inviteLabel(state: BillingSetupRegistrationState): string {
  return state === "no_account" ? "Send invite" : "Remind: add card";
}

export default function BillingSetupPage() {
  const [status, setStatus] = useState<"all" | BillingSetupRegistrationState>("all");
  const [q, setQ] = useState("");
  const [toast, setToast] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const params = { status, q: q || undefined };
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.admin.billingSetup(params),
    queryFn: () => fetchBillingSetup(params),
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["admin", "billing", "setup"] });

  const inviteMutation = useMutation({
    mutationFn: inviteBillingSetupParent,
    onSuccess: (result) => {
      if (result.action === "not_applicable") {
        setToast("Already has a card on file.");
      } else if (result.ok) {
        setToast(
          result.action === "login_invite" ? "Login invite sent." : "Add-card reminder sent.",
        );
      } else {
        setToast(`Invite failed: ${result.failed_reason ?? "unknown error"}`);
      }
      invalidate();
    },
    onError: (err: Error) => setToast(`Invite failed: ${err.message}`),
  });

  const chargeMutation = useMutation({
    mutationFn: chargeBillingSetupParent,
    onSuccess: (result) => {
      if (result.success) {
        setToast(`Charged ${formatCents(result.balance_due_cents === 0 ? 0 : result.balance_due_cents)} successfully.`);
      } else if (result.requires_action) {
        setToast("Charge requires additional verification (3DS) — ask the parent to complete it.");
      } else {
        setToast(`Charge declined${result.decline_code ? `: ${result.decline_code}` : "."}`);
      }
      invalidate();
    },
    onError: (err: Error) => setToast(`Charge failed: ${err.message}`),
  });

  const autopayMutation = useMutation({
    mutationFn: enableBillingSetupAutopay,
    onSuccess: (result) => {
      setToast(`Autopay enabled for ${result.enabled_count} of ${result.eligible_count} eligible children.`);
      invalidate();
    },
    onError: (err: Error) => setToast(`Enable autopay failed: ${err.message}`),
  });

  const summary = data?.summary;

  return (
    <div className="flex flex-col gap-6">
      {toast && (
        <div className="rounded-md border border-slate-200 bg-white px-4 py-2 text-sm text-slate-700 shadow-sm">
          {toast}
          <button className="ml-3 text-slate-400 hover:text-slate-600" onClick={() => setToast(null)}>
            ×
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        <Card p={20}>
          <Overline>Families</Overline>
          <BigNum>{summary?.families_total ?? "—"}</BigNum>
        </Card>
        <Card p={20}>
          <Overline>Registered</Overline>
          <BigNum color="#16a34a">{summary?.families_registered ?? "—"}</BigNum>
        </Card>
        <Card p={20}>
          <Overline>Missing a card</Overline>
          <BigNum color="#d97706">{summary?.families_no_card ?? "—"}</BigNum>
        </Card>
        <Card p={20}>
          <Overline>Outstanding</Overline>
          <BigNum size={28}>{formatCents(summary?.outstanding_total_cents ?? 0)}</BigNum>
        </Card>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex gap-1 rounded-md border border-slate-200 bg-white p-1">
          {FILTERS.map((f) => (
            <button
              key={f.value}
              onClick={() => setStatus(f.value)}
              className={`rounded px-3 py-1.5 text-sm font-medium ${
                status === f.value ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search parent name or email…"
          className="w-64 rounded-md border border-slate-200 px-3 py-1.5 text-sm"
        />
      </div>

      <Card p={0}>
        {isLoading ? (
          <div className="p-8 text-center text-sm text-slate-500">Loading…</div>
        ) : isError ? (
          <div className="p-8 text-center text-sm text-red-600">Failed to load Billing Setup.</div>
        ) : !data || data.rows.length === 0 ? (
          <div className="p-8 text-center text-sm text-slate-500">No families match this filter.</div>
        ) : (
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-xs uppercase text-slate-500">
                <th className="px-4 py-3">Parent</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Card</th>
                <th className="px-4 py-3">Autopay</th>
                <th className="px-4 py-3">Outstanding</th>
                <th className="px-4 py-3">Invited</th>
                <th className="px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row) => (
                <BillingSetupTableRow
                  key={row.parent_id}
                  row={row}
                  onInvite={() => inviteMutation.mutate(row.parent_id)}
                  onCharge={() => chargeMutation.mutate(row.parent_id)}
                  onEnableAutopay={() => autopayMutation.mutate(row.parent_id)}
                  isInviting={inviteMutation.isPending && inviteMutation.variables === row.parent_id}
                  isCharging={chargeMutation.isPending && chargeMutation.variables === row.parent_id}
                  isEnablingAutopay={
                    autopayMutation.isPending && autopayMutation.variables === row.parent_id
                  }
                />
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

function BillingSetupTableRow({
  row,
  onInvite,
  onCharge,
  onEnableAutopay,
  isInviting,
  isCharging,
  isEnablingAutopay,
}: {
  row: BillingSetupRow;
  onInvite: () => void;
  onCharge: () => void;
  onEnableAutopay: () => void;
  isInviting: boolean;
  isCharging: boolean;
  isEnablingAutopay: boolean;
}) {
  const chip = stateChip(row.registration_state);
  const canCharge = row.registration_state === "card_on_file" && row.outstanding_balance_cents > 0;
  const canEnableAutopay =
    row.registration_state === "card_on_file" && row.autopay_eligible_count > row.autopay_active_count;

  return (
    <tr className="border-b border-slate-100 last:border-0">
      <td className="px-4 py-3">
        <div className="font-medium text-slate-900">{row.parent_name}</div>
        <div className="text-xs text-slate-500">{row.parent_email ?? "—"}</div>
        <div className="mt-1 flex flex-wrap gap-1">
          {row.students.map((s) => (
            <span
              key={s.student_id}
              className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600"
            >
              {s.full_name}
            </span>
          ))}
        </div>
      </td>
      <td className="px-4 py-3">
        <Chip variant={chip.variant} label={chip.label} />
      </td>
      <td className="px-4 py-3 text-slate-700">
        {row.card_label ? `${row.card_label} ···· ${row.card_last4 ?? "????"}` : "—"}
      </td>
      <td className="px-4 py-3 text-slate-700">
        {row.autopay_active_count > 0 || row.autopay_eligible_count > 0
          ? `${row.autopay_active_count}/${row.autopay_active_count + row.autopay_eligible_count} children`
          : "—"}
      </td>
      <td className="px-4 py-3 text-slate-700">{formatCents(row.outstanding_balance_cents)}</td>
      <td className="px-4 py-3 text-slate-500">
        {row.last_invited_at ? formatDate(row.last_invited_at) : "—"}
      </td>
      <td className="px-4 py-3">
        <div className="flex flex-wrap gap-2">
          {row.registration_state !== "card_on_file" && (
            <Button size="sm" variant="secondary" onClick={onInvite} disabled={isInviting}>
              {isInviting ? "Sending…" : row.last_invited_at ? `Resend: ${inviteLabel(row.registration_state)}` : inviteLabel(row.registration_state)}
            </Button>
          )}
          {canCharge && (
            <Button size="sm" variant="primary" onClick={onCharge} disabled={isCharging}>
              {isCharging ? "Charging…" : "Charge now"}
            </Button>
          )}
          {canEnableAutopay && (
            <Button size="sm" variant="secondary" onClick={onEnableAutopay} disabled={isEnablingAutopay}>
              {isEnablingAutopay ? "Enabling…" : "Enable autopay"}
            </Button>
          )}
        </div>
      </td>
    </tr>
  );
}
