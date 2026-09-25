"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getBillingRules, updateBillingRules } from "@/lib/api/admin";
import {
  canSave,
  diffForm,
  isListRow,
  saveSummary,
  toForm,
  turnsLateFeeOn,
  type BillingRuleGroup,
  type BillingRuleRow,
  type BillingRulesForm,
  type MoneyCodec,
} from "@/lib/billing-rules-form";
import { formatCents, parseDollarsToCents } from "@/lib/money";
import { queryKeys } from "@/lib/query/keys";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";
import { useReportSettingsDirty } from "@/components/admin/settings/settings-dirty-context";

/**
 * Settings → Billing rules (spec 2026-09-07-billing-rules-design).
 *
 * Replaces the Fees and Invoice schedule panels. Every number that decides
 * when money moves is on this page, grouped by the decision it serves and
 * marked editable or fixed. Fixed rows are stated, not hidden, and are
 * visibly not inputs — no box, no cursor — because "cancel mid-month = full
 * month owed" is a real answer even though there is no switch beside it.
 */
/** `lib/money` is the one money formatter and parser; the view model takes it. */
const MONEY: MoneyCodec = { format: formatCents, parse: parseDollarsToCents };

export function BillingRulesPanel() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: queryKeys.admin.billingRules(), queryFn: getBillingRules });
  const [form, setForm] = useState<BillingRulesForm>({});
  const [saved, setSaved] = useState(false);
  const [lateFeeAcknowledged, setLateFeeAcknowledged] = useState(false);

  useEffect(() => {
    if (query.data) setForm(toForm(query.data));
  }, [query.data]);

  const diff = useMemo(() => diffForm(query.data, form, MONEY), [query.data, form]);
  // Money audit X4: switching the fee on starts real charges on the next
  // hourly run, so the owner must acknowledge it before Save is enabled.
  const needsLateFeeAck = turnsLateFeeOn(query.data, diff);
  const saveEnabled = canSave(diff) && (!needsLateFeeAck || lateFeeAcknowledged);
  const mutation = useMutation({
    mutationFn: () => updateBillingRules(diff.payload),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.admin.billingRules(), data);
      // The cancellation fee and notice are shared with the Self-service tab;
      // drop its cached copy so it never shows (or re-saves) the old values.
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.selfServicePolicy() });
      setForm(toForm(data));
      setLateFeeAcknowledged(false);
      setSaved(true);
    },
  });

  const errors = { ...diff.errors, ...parseServerErrors(mutation.error) };
  // Edits that are typed but not yet valid still count as unsaved work:
  // the tab strip must warn before it throws them away (#863).
  useReportSettingsDirty(
    "billing-rules",
    diff.changed.length > 0 || Object.keys(diff.errors).length > 0
  );

  return (
    <section data-testid="admin-settings-billing-rules" className="space-y-4">
      {query.isError && (
        <p className="text-sm text-red-700" role="alert">
          Could not load the billing rules.
        </p>
      )}
      {(query.data?.groups ?? []).map((group) => (
        <RuleGroupCard
          key={group.key}
          group={group}
          form={form}
          errors={errors}
          onChange={(key, value) => {
            setSaved(false);
            setForm((prev) => ({ ...prev, [key]: value }));
          }}
        />
      ))}
      {query.data && needsLateFeeAck && (
        <div
          role="alert"
          className="max-w-3xl rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900"
          data-testid="billing-rules-late-fee-warning"
        >
          <p className="font-semibold">You are turning on a late fee.</p>
          <p className="mt-1">
            From the next hourly run, the fee is added once to each unpaid invoice whose grace
            period ends today or later. Invoices that are already overdue are not charged. Autopay
            invoices wait until their card retries finish. Parents see the fee on the invoice and in
            the next reminder.
          </p>
          <label className="mt-3 flex items-start gap-2 font-medium">
            <input
              type="checkbox"
              className="mt-1"
              checked={lateFeeAcknowledged}
              onChange={(event) => setLateFeeAcknowledged(event.target.checked)}
              data-testid="billing-rules-late-fee-ack"
            />
            <span>I understand parents will be charged this fee.</span>
          </label>
        </div>
      )}
      {query.data && (
        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant={saveEnabled ? "volt" : "secondary"}
            size="sm"
            disabled={!saveEnabled || mutation.isPending}
            onClick={() => mutation.mutate()}
            data-testid="billing-rules-save"
          >
            {mutation.isPending ? "Saving…" : saveSummary(diff)}
          </Button>
          {saved && !mutation.isPending && (
            <span className="text-sm text-rally-muted" data-testid="billing-rules-saved">
              Saved.
            </span>
          )}
          {mutation.isError && (
            <span className="text-sm text-red-700" role="alert">
              {savedFieldsMessage(mutation.error) ?? "Could not save the billing rules."}
            </span>
          )}
        </div>
      )}
    </section>
  );
}

function RuleGroupCard({
  group,
  form,
  errors,
  onChange,
}: {
  group: BillingRuleGroup;
  form: BillingRulesForm;
  errors: Record<string, string>;
  onChange: (key: string, value: string) => void;
}) {
  return (
    <Card p={24} className="max-w-3xl" data-testid={`billing-rules-group-${group.key}`}>
      <Overline>{group.title}</Overline>
      {/* The caveat sits ABOVE the inputs so it is read before they are filled in. */}
      {group.note && (
        <p className="mt-2 text-sm text-rally-muted" data-testid={`billing-rules-note-${group.key}`}>
          {group.note}
        </p>
      )}
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        {group.rows.map((row) =>
          row.editable ? (
            <EditableRule
              key={row.key}
              row={row}
              value={form[row.key] ?? ""}
              error={errors[row.key]}
              onChange={(value) => onChange(row.key, value)}
            />
          ) : (
            <FixedRule key={row.key} row={row} />
          ),
        )}
      </div>
    </Card>
  );
}

function EditableRule({
  row,
  value,
  error,
  onChange,
}: {
  row: BillingRuleRow;
  value: string;
  error?: string;
  onChange: (value: string) => void;
}) {
  // Issue #774: `reminder_days` holds a LIST ("15, 20"), so it is a text box
  // rather than a number spinner, and an empty box is a real value meaning
  // "send no reminders" — the off switch the owner asked for.
  const list = isListRow(row);
  return (
    <label className="grid gap-1.5 text-sm font-medium text-rally-ink">
      {row.unit === "cents" ? `${row.label} ($)` : row.label}
      <input
        type={list ? "text" : "number"}
        min={list ? undefined : inputBound(row, row.min_value)}
        max={list ? undefined : inputBound(row, row.max_value)}
        step={list ? undefined : row.unit === "cents" ? "0.01" : "1"}
        inputMode={list ? "numeric" : row.unit === "cents" ? "decimal" : "numeric"}
        placeholder={list ? "15, 20 — empty to send none" : undefined}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={error ? true : undefined}
        className={`h-10 rounded-lg border bg-white px-3 font-mono text-sm tabular-nums outline-none focus:border-blue-500 ${
          error ? "border-red-500" : "border-rally-line"
        }`}
        data-testid={`billing-rules-input-${row.key}`}
      />
      {error && (
        <span className="text-xs text-red-700" role="alert" data-testid={`billing-rules-error-${row.key}`}>
          {error}
        </span>
      )}
      {!error && row.detail && <span className="text-xs text-rally-muted">{row.detail}</span>}
    </label>
  );
}

/** A stated value with its explanation. Visibly not an input. */
function FixedRule({ row }: { row: BillingRuleRow }) {
  return (
    <div className="grid gap-0.5" data-testid={`billing-rules-fixed-${row.key}`}>
      <span className="text-sm font-medium text-rally-ink">{row.label}</span>
      <span className="text-sm text-rally-muted">{row.display}</span>
      {row.detail && <span className="text-xs text-rally-muted">{row.detail}</span>}
    </div>
  );
}

/** min/max arrive in the row's stored unit; a cents input shows dollars. */
function inputBound(row: BillingRuleRow, bound: number | null): number | undefined {
  if (bound === null) return undefined;
  return row.unit === "cents" ? bound / 100 : bound;
}

/**
 * The backend 422 names the offending field (`{field, message}`), so a bound
 * violation renders against that input rather than as a page-level banner.
 */
function parseServerErrors(error: unknown): Record<string, string> {
  const detail = detailOf(error);
  if (detail && typeof detail.field === "string") {
    const message = typeof detail.message === "string" ? detail.message : "Not allowed.";
    return { [detail.field]: message };
  }
  return {};
}

/** A 500 from a partial write says which fields did land. */
function savedFieldsMessage(error: unknown): string | null {
  const detail = detailOf(error);
  if (detail && Array.isArray(detail.saved_fields)) {
    const list = detail.saved_fields.map(String);
    return list.length > 0
      ? `Only these were saved: ${list.join(", ")}. Try the rest again.`
      : "Nothing was saved. Try again.";
  }
  return null;
}

function detailOf(error: unknown): Record<string, unknown> | null {
  const details = (error as { details?: unknown } | null)?.details;
  return details && typeof details === "object" ? (details as Record<string, unknown>) : null;
}
