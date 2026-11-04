"use client";

import { useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Card, Chip, FormField, Overline, Th } from "@/components/ds";
import {
  billingMonthsFrom,
  cancelPlanPriceChange,
  formatBillingMonth,
  previewPlanPriceChange,
  schedulePlanPriceChange,
  type PlanPriceChangePreview,
  type PricingPlan,
} from "@/lib/api/v2/pricing";
import { formatCents } from "@/lib/money";
import { queryKeys } from "@/lib/query/keys";

/** How many months the "Apply from" list offers, starting at the earliest. */
const MONTH_CHOICES = 12;

const inputClass =
  "h-10 w-full rounded-md border border-rally-line bg-white px-3 text-sm outline-none focus:border-blue-500";

function dollarsToCents(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed) || parsed < 0) return null;
  return Math.round(parsed * 100);
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message && error.message !== "Request failed"
    ? error.message
    : fallback;
}

/**
 * "Change a plan price · Preview first" (Settings overhaul Phase 6 PR 26).
 *
 * The owner picks a plan, a new price and a future month. The preview says
 * which classes and how many billed students it reaches, from which invoice;
 * "Apply from <Month>" records it. Invoices already sent never change, and
 * classes on a custom price are listed as not affected. A scheduled change
 * can be cancelled until its month starts.
 *
 * Rendered only for the owner (the whole Pricing page is owner-only); the
 * API refuses anyone else with a 403.
 */
export function ChangePlanPriceCard({ plans }: { plans: PricingPlan[] }) {
  const queryClient = useQueryClient();
  const [planId, setPlanId] = useState("");
  const [price, setPrice] = useState("");
  const [month, setMonth] = useState<string | null>(null);

  const scheduled = plans.filter((plan) => plan.scheduled_change_id);
  const choosable = plans.filter((plan) => plan.is_active && !plan.scheduled_change_id);
  const plan = choosable.find((p) => p.plan_id === planId) ?? null;
  const newPriceCents = dollarsToCents(price);
  const samePrice = plan !== null && newPriceCents === plan.price_cents;
  const canPreview = plan !== null && newPriceCents !== null && !samePrice;

  const previewQuery = useQuery({
    queryKey: queryKeys.admin.pricingPriceChangePreview(planId, newPriceCents ?? -1, month),
    queryFn: () =>
      previewPlanPriceChange({
        planId,
        newPriceCents: newPriceCents ?? 0,
        effectivePeriod: month,
      }),
    enabled: canPreview,
    retry: false,
    placeholderData: keepPreviousData,
  });
  const preview = canPreview ? previewQuery.data : undefined;

  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.pricing() }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.admin.sessionTypes(),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.admin.scheduledClassFees(),
      }),
    ]);

  const applyMutation = useMutation({
    mutationFn: (current: PlanPriceChangePreview) =>
      schedulePlanPriceChange({
        plan_id: current.plan_id,
        new_price_cents: current.new_cents,
        effective_period: current.effective_period,
      }),
    onSuccess: () => {
      setPlanId("");
      setPrice("");
      setMonth(null);
      void refresh();
    },
  });

  const cancelMutation = useMutation({
    mutationFn: (changeId: string) => cancelPlanPriceChange(changeId),
    onSuccess: () => void refresh(),
  });

  function choosePlan(id: string) {
    setPlanId(id);
    setMonth(null);
    applyMutation.reset();
  }

  const months = preview ? billingMonthsFrom(preview.earliest_period, MONTH_CHOICES) : [];

  return (
    <Card data-testid="pricing-change-price">
      <div className="flex flex-wrap items-center gap-2">
        <Overline>Change a plan price</Overline>
        <Chip variant="pending" label="PREVIEW FIRST" />
      </div>
      <p className="mt-1 max-w-2xl text-sm text-rally-muted">
        A new price reaches the classes linked to the plan from a future month. Invoices already
        sent never change.
      </p>

      {scheduled.length > 0 && (
        <ul className="mt-4 space-y-2" data-testid="pricing-scheduled-changes">
          {scheduled.map((row) => (
            <li
              key={row.plan_id}
              data-testid="pricing-scheduled-change"
              className="flex flex-wrap items-center justify-between gap-3 rounded-md bg-status-amber-50 px-3 py-2 text-sm text-status-amber-800"
            >
              <span>
                <b>{row.name}</b> {formatCents(row.price_cents)} &rarr;{" "}
                {formatCents(row.scheduled_cents ?? 0)} from the{" "}
                {formatBillingMonth(row.scheduled_from ?? "", { year: true })} invoice.
              </span>
              <Button
                variant="secondary"
                size="sm"
                disabled={cancelMutation.isPending}
                onClick={() => cancelMutation.mutate(row.scheduled_change_id ?? "")}
                data-testid="pricing-price-change-cancel"
              >
                {cancelMutation.isPending && cancelMutation.variables === row.scheduled_change_id
                  ? "Cancelling..."
                  : "Cancel change"}
              </Button>
            </li>
          ))}
        </ul>
      )}
      {cancelMutation.isError && (
        <p role="alert" className="mt-2 text-sm text-status-red-800">
          {errorMessage(cancelMutation.error, "Could not cancel the change. Try again.")}
        </p>
      )}

      <div className="mt-4 grid gap-4 sm:grid-cols-3">
        <FormField label="Plan" htmlFor="price-change-plan">
          <select
            id="price-change-plan"
            data-testid="pricing-price-change-plan"
            value={planId}
            onChange={(event) => choosePlan(event.target.value)}
            className={inputClass}
          >
            <option value="">Choose a plan</option>
            {choosable.map((option) => (
              <option key={option.plan_id} value={option.plan_id}>
                {option.name} ({formatCents(option.price_cents)})
              </option>
            ))}
          </select>
        </FormField>
        <FormField
          label="New price ($ / month)"
          htmlFor="price-change-price"
          error={samePrice ? "That is the current price." : undefined}
        >
          <input
            id="price-change-price"
            data-testid="pricing-price-change-price"
            type="number"
            min="0"
            step="0.01"
            inputMode="decimal"
            value={price}
            onChange={(event) => setPrice(event.target.value)}
            className={`${inputClass} font-mono tabular-nums`}
          />
        </FormField>
        <FormField label="Apply from" htmlFor="price-change-month">
          <select
            id="price-change-month"
            data-testid="pricing-price-change-month"
            value={preview?.effective_period ?? ""}
            disabled={!preview}
            onChange={(event) => setMonth(event.target.value)}
            className={`${inputClass} disabled:bg-neutral-100`}
          >
            {!preview && <option value="">Pick a plan and price</option>}
            {months.map((value) => (
              <option key={value} value={value}>
                {formatBillingMonth(value, { year: true })}
              </option>
            ))}
          </select>
        </FormField>
      </div>

      {canPreview && previewQuery.isError && (
        <p role="alert" className="mt-3 text-sm text-status-red-800">
          {errorMessage(previewQuery.error, "Could not preview this change. Try again.")}
        </p>
      )}

      {preview && <PriceChangePreview preview={preview} />}

      {applyMutation.isError && (
        <p role="alert" className="mt-3 text-sm text-status-red-800">
          {errorMessage(applyMutation.error, "Could not apply the change. Try again.")}
        </p>
      )}
      {applyMutation.isSuccess && (
        <p
          role="status"
          className="mt-3 text-sm text-rally-muted"
          data-testid="pricing-price-change-done"
        >
          Scheduled. It shows on the plan and its classes until it takes effect.
        </p>
      )}

      {preview && (
        <div className="mt-4 flex justify-end">
          <Button
            variant="volt"
            size="sm"
            disabled={applyMutation.isPending || previewQuery.isFetching}
            onClick={() => applyMutation.mutate(preview)}
            data-testid="pricing-price-change-apply"
          >
            {applyMutation.isPending
              ? "Applying..."
              : `Apply from ${formatBillingMonth(preview.effective_period)}`}
          </Button>
        </div>
      )}
    </Card>
  );
}

export function PriceChangePreview({ preview }: { preview: PlanPriceChangePreview }) {
  const month = formatBillingMonth(preview.effective_period);
  const classes = preview.total_classes === 1 ? "class" : "classes";
  const students = preview.total_students === 1 ? "student" : "students";
  return (
    <div className="mt-4 space-y-3" data-testid="pricing-price-change-preview">
      <p className="text-sm text-rally-ink" data-testid="pricing-price-change-summary">
        {preview.plan_name} {formatCents(preview.old_cents)} &rarr; {formatCents(preview.new_cents)}
        : {preview.total_classes} {classes}, {preview.total_students} {students} affected, from the{" "}
        <b>{month}</b> invoice. Invoices already sent never change.
      </p>
      {preview.classes.length > 0 && (
        <div className="overflow-x-auto rounded-md border border-rally-line">
          <table className="w-full min-w-[480px] text-sm">
            <thead>
              <tr className="border-b border-rally-line">
                <Th>Class</Th>
                <Th align="right">Students billed</Th>
                <Th align="right">Now</Th>
                <Th align="right">From {month}</Th>
              </tr>
            </thead>
            <tbody>
              {preview.classes.map((row) => (
                <tr
                  key={row.session_id}
                  data-testid="pricing-price-change-class"
                  className="border-b border-rally-line last:border-0"
                >
                  <td className="px-4 py-2 font-semibold text-rally-ink">{row.title}</td>
                  <td className="px-4 py-2 text-right font-mono tabular-nums">{row.students}</td>
                  <td className="px-4 py-2 text-right font-mono tabular-nums">
                    {formatCents(row.old_cents)}
                  </td>
                  <td className="px-4 py-2 text-right font-mono tabular-nums">
                    {formatCents(row.new_cents)}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t border-rally-line">
                <td className="px-4 py-2 font-semibold text-rally-ink">Per month</td>
                <td className="px-4 py-2 text-right font-mono tabular-nums">
                  {preview.total_students}
                </td>
                <td className="px-4 py-2 text-right font-mono tabular-nums">
                  {formatCents(preview.old_monthly_cents)}
                </td>
                <td className="px-4 py-2 text-right font-mono tabular-nums">
                  {formatCents(preview.new_monthly_cents)}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
      {preview.classes.length === 0 && (
        <p className="text-sm text-rally-muted">
          No class is linked to this plan, so no bill changes. The plan price still moves in {month}
          .
        </p>
      )}
      {preview.not_affected.length > 0 && (
        <p className="text-xs text-rally-subtle" data-testid="pricing-price-change-not-affected">
          Not affected (custom price): {preview.not_affected.map((row) => row.title).join(", ")}.
        </p>
      )}
    </div>
  );
}
