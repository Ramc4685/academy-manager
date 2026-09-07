"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getBillingRules, updateBillingRules } from "@/lib/api/admin";
import {
  canSave,
  diffForm,
  saveSummary,
  toForm,
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

  useEffect(() => {
    if (query.data) setForm(toForm(query.data));
  }, [query.data]);

  const diff = useMemo(() => diffForm(query.data, form, MONEY), [query.data, form]);
  const mutation = useMutation({
    mutationFn: () => updateBillingRules(diff.payload),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.admin.billingRules(), data);
      setForm(toForm(data));
      setSaved(true);
    },
  });

  const errors = { ...diff.errors, ...parseServerErrors(mutation.error) };

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
      {query.data && (
        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant={canSave(diff) ? "volt" : "secondary"}
            size="sm"
            disabled={!canSave(diff) || mutation.isPending}
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
  return (
    <label className="grid gap-1.5 text-sm font-medium text-rally-ink">
      {row.unit === "cents" ? `${row.label} ($)` : row.label}
      <input
        type="number"
        min={inputBound(row, row.min_value)}
        max={inputBound(row, row.max_value)}
        step={row.unit === "cents" ? "0.01" : "1"}
        inputMode={row.unit === "cents" ? "decimal" : "numeric"}
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
