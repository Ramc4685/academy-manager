"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getAdminFees,
  updateAdminFees,
  type AdminFeesView,
  type UpdateAdminFeesRequest,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";

type FeesForm = Record<keyof AdminFeesView, string>;

function centsToDollarInput(cents: number | null | undefined): string {
  if (cents === null || cents === undefined) return "";
  return (cents / 100).toFixed(2);
}

function dollarsToCentsInput(dollars: string): number | null {
  if (dollars === "") return null;
  return Math.round(Number(dollars) * 100);
}

function normalize(data: AdminFeesView | null | undefined): FeesForm {
  return {
    default_monthly_cents: data?.default_monthly_cents?.toString() ?? "",
    late_fee_cents: centsToDollarInput(data?.late_fee_cents),
    grace_days: data?.grace_days?.toString() ?? "",
  };
}

function toPayload(original: FeesForm, form: FeesForm): UpdateAdminFeesRequest {
  const payload: UpdateAdminFeesRequest = {};
  (Object.keys(form) as Array<keyof FeesForm>).forEach((key) => {
    if (form[key] !== original[key]) {
      payload[key] =
        key === "late_fee_cents"
          ? dollarsToCentsInput(form[key])
          : form[key] === ""
            ? null
            : Number(form[key]);
    }
  });
  return payload;
}

export function FeesPanel() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<FeesForm>(() => normalize(null));
  const [saved, setSaved] = useState(false);
  const query = useQuery({ queryKey: queryKeys.admin.fees(), queryFn: getAdminFees });
  const original = useMemo(() => normalize(query.data), [query.data]);

  useEffect(() => {
    if (query.data) setForm(normalize(query.data));
  }, [query.data]);

  const payload = toPayload(original, form);
  const dirty = Object.keys(payload).length > 0;
  const mutation = useMutation({
    mutationFn: () => updateAdminFees(payload),
    onSuccess: () => {
      setSaved(true);
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.fees() });
      window.setTimeout(() => setSaved(false), 2000);
    },
  });

  return (
    <section data-testid="admin-settings-fees">
      <Card p={24} className="max-w-3xl">
        <Overline>Late payments</Overline>
        <div className="mt-5 grid gap-4 md:grid-cols-2">
          <NumberField
            label="Late fee ($)"
            value={form.late_fee_cents}
            step="0.01"
            onChange={(value) => setForm((prev) => ({ ...prev, late_fee_cents: value }))}
          />
          <NumberField
            label="Grace days"
            value={form.grace_days}
            onChange={(value) => setForm((prev) => ({ ...prev, grace_days: value }))}
          />
        </div>
        <Footer
          dirty={dirty}
          pending={mutation.isPending}
          saved={saved}
          error={query.isError || mutation.isError ? mutation.error ?? query.error : null}
          onSave={() => mutation.mutate()}
        />
      </Card>
    </section>
  );
}

function NumberField({
  label,
  value,
  step = "1",
  onChange,
}: {
  label: string;
  value: string;
  step?: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="grid gap-1.5 text-sm font-medium text-rally-ink">
      {label}
      <input
        type="number"
        min="0"
        step={step}
        inputMode={step === "0.01" ? "decimal" : "numeric"}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-10 rounded-md border border-rally-line bg-white px-3 font-mono text-sm tabular-nums outline-none focus:border-blue-500"
      />
    </label>
  );
}

function Footer({
  dirty,
  pending,
  saved,
  error,
  onSave,
}: {
  dirty: boolean;
  pending: boolean;
  saved: boolean;
  error: Error | null;
  onSave: () => void;
}) {
  return (
    <div className="mt-6 flex flex-wrap items-center gap-3">
      <Button variant={dirty ? "volt" : "secondary"} size="sm" disabled={!dirty || pending} onClick={onSave}>
        {pending ? "Saving..." : "Save changes"}
      </Button>
      {saved && <p className="text-sm font-medium text-emerald-700">Saved.</p>}
      {error && <p className="text-sm font-medium text-red-700">{error.message}</p>}
    </div>
  );
}
