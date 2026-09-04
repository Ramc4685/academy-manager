"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getInvoiceSchedule, setInvoiceSchedule } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";

/**
 * Monthly invoicing schedule (issue #651). These two numbers drive the whole
 * autopay rhythm: invoices are generated on `billing_day`, fall due
 * `invoice_due_days` later, and the first autopay attempt runs on the due date
 * (09:00 academy time). Keep them visible so nobody is surprised by a charge.
 */
export function InvoiceSchedulePanel() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: queryKeys.admin.invoiceSchedule(),
    queryFn: getInvoiceSchedule,
  });
  const [billingDay, setBillingDay] = useState("1");
  const [dueDays, setDueDays] = useState("7");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (query.data) {
      setBillingDay(String(query.data.billing_day));
      setDueDays(String(query.data.invoice_due_days));
    }
  }, [query.data]);

  const mutation = useMutation({
    mutationFn: setInvoiceSchedule,
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.admin.invoiceSchedule(), data);
      setSaved(true);
    },
  });

  const dirty =
    query.data !== undefined &&
    (String(query.data.billing_day) !== billingDay || String(query.data.invoice_due_days) !== dueDays);
  const billingDayNum = Number(billingDay);
  const dueDaysNum = Number(dueDays);
  const valid =
    Number.isInteger(billingDayNum) &&
    billingDayNum >= 1 &&
    billingDayNum <= 28 &&
    Number.isInteger(dueDaysNum) &&
    dueDaysNum >= 0 &&
    dueDaysNum <= 60;

  return (
    <Card p={24} className="max-w-3xl" data-testid="invoice-schedule-panel">
      <Overline>Invoice schedule</Overline>
      <h2 className="mt-1 font-display text-lg font-semibold text-rally-ink">Monthly invoicing and autopay</h2>
      <p className="mt-1 text-sm text-rally-muted">
        Invoices are generated on the billing day and fall due after the grace window. Autopay charges the
        saved card on the due date at 9:00 AM academy time. Parents on autopay receive a notice when the
        invoice is generated and a receipt after the charge.
      </p>
      {query.isError && (
        <p className="mt-3 text-sm text-red-700" role="alert">
          Could not load the invoice schedule.
        </p>
      )}
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <label className="grid gap-1.5 text-sm font-medium text-rally-ink">
          Billing day of month (1–28)
          <input
            type="number"
            min={1}
            max={28}
            inputMode="numeric"
            value={billingDay}
            onChange={(e) => {
              setSaved(false);
              setBillingDay(e.target.value);
            }}
            className="rounded-lg border border-rally-line bg-white px-3 py-2 text-rally-ink"
            data-testid="invoice-schedule-billing-day"
          />
        </label>
        <label className="grid gap-1.5 text-sm font-medium text-rally-ink">
          Days until due (0–60)
          <input
            type="number"
            min={0}
            max={60}
            inputMode="numeric"
            value={dueDays}
            onChange={(e) => {
              setSaved(false);
              setDueDays(e.target.value);
            }}
            className="rounded-lg border border-rally-line bg-white px-3 py-2 text-rally-ink"
            data-testid="invoice-schedule-due-days"
          />
        </label>
      </div>
      <div className="mt-4 flex items-center gap-3">
        <Button
          variant={dirty && valid ? "volt" : "secondary"}
          size="sm"
          disabled={!dirty || !valid || mutation.isPending}
          onClick={() =>
            mutation.mutate({ billing_day: billingDayNum, invoice_due_days: dueDaysNum })
          }
          data-testid="invoice-schedule-save"
        >
          {mutation.isPending ? "Saving…" : "Save schedule"}
        </Button>
        {saved && <span className="text-sm text-rally-muted">Saved.</span>}
        {mutation.isError && (
          <span className="text-sm text-red-700" role="alert">
            Could not save the schedule.
          </span>
        )}
      </div>
    </Card>
  );
}
