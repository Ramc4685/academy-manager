"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getPayrollSettings,
  updatePayrollSettings,
  type PayrollSettings,
} from "@/lib/api/v2/payroll";
import { queryKeys } from "@/lib/query/keys";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";
import { useReportSettingsDirty } from "@/components/admin/settings/settings-dirty-context";

type Choice<K extends keyof PayrollSettings> = {
  field: K;
  legend: string;
  options: { value: PayrollSettings[K]; label: string }[];
};

const CANCELLED: Choice<"payroll_cancelled_class_share"> = {
  field: "payroll_cancelled_class_share",
  legend: "When a class is cancelled",
  options: [
    { value: "ran_only", label: "Split the month's tuition across the classes that ran" },
    { value: "all_scheduled", label: "Split it across every scheduled class" },
  ],
};

const MISSING: Choice<"payroll_missing_invoices"> = {
  field: "payroll_missing_invoices",
  legend: "When a class has no invoices for the month",
  options: [
    { value: "block", label: "Block approval until it is invoiced" },
    { value: "pay_zero", label: "Pay $0 for that class" },
  ],
};

/**
 * Settings → Billing rules → Coach payroll (L7). Owner only, like the panel it
 * sits in; the save is audited server side. Percent-of-revenue coaches are paid
 * on the tuition actually invoiced for each class and month; these choices say
 * how that base is counted. A change applies to payout periods generated or
 * recomputed afterwards, never to approved or paid ones.
 */
export function PayrollSettingsCard() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: queryKeys.admin.payrollSettings(),
    queryFn: getPayrollSettings,
  });
  const [form, setForm] = useState<PayrollSettings | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    if (query.data) setForm(query.data);
  }, [query.data]);

  const dirty =
    Boolean(query.data && form) && JSON.stringify(form) !== JSON.stringify(query.data);
  useReportSettingsDirty("payroll-settings", dirty);

  const mutation = useMutation({
    mutationFn: () => updatePayrollSettings(form as PayrollSettings),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.admin.payrollSettings(), data);
      setSaved(true);
    },
  });

  const set = <K extends keyof PayrollSettings>(field: K, value: PayrollSettings[K]) => {
    setSaved(false);
    setForm((prev) => (prev ? { ...prev, [field]: value } : prev));
  };

  const radios = <K extends keyof PayrollSettings>(choice: Choice<K>) =>
    form && (
      <fieldset className="mt-4">
        <legend className="text-sm font-medium text-rally-ink">{choice.legend}</legend>
        <div className="mt-2 grid gap-2">
          {choice.options.map((option) => (
            <label key={String(option.value)} className="flex items-center gap-2 text-sm">
              <input
                type="radio"
                name={choice.field}
                checked={form[choice.field] === option.value}
                onChange={() => set(choice.field, option.value)}
                data-testid={`payroll-settings-${choice.field}-${String(option.value)}`}
              />
              {option.label}
            </label>
          ))}
        </div>
      </fieldset>
    );

  return (
    <Card p={24} className="max-w-3xl" data-testid="payroll-settings-card">
      <Overline>Coach payroll</Overline>
      <p className="mt-2 text-sm text-rally-muted">
        Coaches on a percent rate are paid a share of the tuition invoiced for each class and
        month. Changes apply to payslips generated or recomputed afterwards; approved and paid
        payslips never change.
      </p>
      {query.isError && (
        <p className="mt-3 text-sm text-red-700" role="alert">
          Could not load the coach payroll settings.
        </p>
      )}
      {form && (
        <>
          <label className="mt-4 flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.payroll_ach_discount_reduces_base}
              onChange={(e) => set("payroll_ach_discount_reduces_base", e.target.checked)}
              data-testid="payroll-settings-ach"
            />
            The ACH autopay discount reduces the coach&apos;s base
          </label>
          <label className="mt-2 flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.payroll_count_checkout_first_month}
              onChange={(e) => set("payroll_count_checkout_first_month", e.target.checked)}
              data-testid="payroll-settings-checkout"
            />
            Count the first month a family paid at registration checkout
          </label>
          {radios(CANCELLED)}
          {radios(MISSING)}
          <label className="mt-4 flex flex-col gap-1 text-sm">
            <span className="font-medium text-rally-ink">Pay assistant coaches in the app from</span>
            <input
              type="month"
              value={form.payroll_assistant_pay_from ?? ""}
              onChange={(e) => set("payroll_assistant_pay_from", e.target.value || null)}
              className="w-44 rounded-md border border-neutral-200 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-900"
              aria-describedby="payroll-settings-assistant-hint"
              data-testid="payroll-settings-assistant-pay-from"
            />
            <span id="payroll-settings-assistant-hint" className="text-rally-muted">
              Leave empty while assistants are paid outside the app. From this month on, each
              assisted class gets its own line on the assistant&apos;s payslip.
            </span>
          </label>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Button
              variant={dirty ? "volt" : "secondary"}
              size="sm"
              disabled={!dirty || mutation.isPending}
              onClick={() => mutation.mutate()}
              data-testid="payroll-settings-save"
            >
              {mutation.isPending ? "Saving…" : "Save coach payroll"}
            </Button>
            {saved && !mutation.isPending && !dirty && (
              <span className="text-sm text-rally-muted">Saved.</span>
            )}
            {mutation.isError && (
              <span className="text-sm text-red-700" role="alert">
                {mutation.error instanceof Error
                  ? mutation.error.message
                  : "Could not save the coach payroll settings."}
              </span>
            )}
          </div>
        </>
      )}
    </Card>
  );
}
