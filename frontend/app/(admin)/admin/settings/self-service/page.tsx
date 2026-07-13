"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getSelfServicePolicy,
  updateSelfServicePolicy,
  type SelfServicePolicyView,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";

type PolicyForm = {
  absence_notice_min_hours: string;
  makeup_expiry_days: string;
  makeup_requires_notice: boolean;
  cancellation_minimum_notice_days: string;
  cancellation_fee_dollars: string;
  cancellation_effective_timing: "immediate" | "end_of_period";
};

function centsToDollarInput(cents: number | null | undefined): string {
  if (cents === null || cents === undefined) return "";
  return (cents / 100).toFixed(2);
}

function dollarsToCents(dollars: string): number {
  const value = Number(dollars);
  return Number.isFinite(value) ? Math.round(value * 100) : 0;
}

function normalize(data: SelfServicePolicyView | null | undefined): PolicyForm {
  return {
    absence_notice_min_hours: data?.absence_notice_min_hours?.toString() ?? "",
    makeup_expiry_days: data?.makeup_expiry_days?.toString() ?? "",
    makeup_requires_notice: data?.makeup_requires_notice ?? false,
    cancellation_minimum_notice_days: data?.cancellation_minimum_notice_days?.toString() ?? "",
    cancellation_fee_dollars: centsToDollarInput(data?.cancellation_fee_cents),
    cancellation_effective_timing: data?.cancellation_effective_timing ?? "immediate",
  };
}

function isDirty(original: PolicyForm, form: PolicyForm): boolean {
  return (Object.keys(form) as Array<keyof PolicyForm>).some((key) => form[key] !== original[key]);
}

export default function SelfServiceSettingsPage() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<PolicyForm>(() => normalize(null));
  const [saved, setSaved] = useState(false);
  const query = useQuery({
    queryKey: queryKeys.admin.selfServicePolicy(),
    queryFn: getSelfServicePolicy,
  });
  const original = useMemo(() => normalize(query.data), [query.data]);

  useEffect(() => {
    if (query.data) setForm(normalize(query.data));
  }, [query.data]);

  const dirty = isDirty(original, form);
  const mutation = useMutation({
    mutationFn: () =>
      updateSelfServicePolicy({
        absence_notice_min_hours: Number(form.absence_notice_min_hours) || 0,
        makeup_expiry_days: Number(form.makeup_expiry_days) || 0,
        makeup_requires_notice: form.makeup_requires_notice,
        cancellation_minimum_notice_days: Number(form.cancellation_minimum_notice_days) || 0,
        cancellation_fee_cents: dollarsToCents(form.cancellation_fee_dollars),
        cancellation_effective_timing: form.cancellation_effective_timing,
      }),
    onSuccess: () => {
      setSaved(true);
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.selfServicePolicy() });
      window.setTimeout(() => setSaved(false), 2000);
    },
  });

  return (
    <section data-testid="admin-settings-self-service" className="space-y-6">
      <div>
        <h1 className="font-display text-2xl font-bold tracking-tight text-rally-ink">Self-service policy</h1>
        <p className="mt-0.5 text-sm text-rally-subtle">
          Rules that govern parent absence notices, makeup requests, and self-cancellation
        </p>
      </div>

      {query.isError ? (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load self-service policy.
        </p>
      ) : query.isLoading ? (
        <div className="h-48 animate-pulse rounded-xl bg-neutral-100 dark:bg-neutral-800" />
      ) : (
        <Card p={24} className="max-w-3xl">
          <Overline>Absences &amp; makeups</Overline>
          <div className="mt-5 grid gap-4 md:grid-cols-2">
            <NumberField
              label="Minimum absence notice (hours)"
              value={form.absence_notice_min_hours}
              onChange={(value) => setForm((prev) => ({ ...prev, absence_notice_min_hours: value }))}
            />
            <NumberField
              label="Makeup expiry (days)"
              value={form.makeup_expiry_days}
              onChange={(value) => setForm((prev) => ({ ...prev, makeup_expiry_days: value }))}
            />
          </div>
          <label className="mt-4 flex items-center gap-2 text-sm font-medium text-rally-ink">
            <input
              type="checkbox"
              checked={form.makeup_requires_notice}
              onChange={(e) => setForm((prev) => ({ ...prev, makeup_requires_notice: e.target.checked }))}
            />
            Makeup requests require an on-time absence notice
          </label>

          <div className="mt-8">
            <Overline>Cancellation</Overline>
          </div>
          <div className="mt-5 grid gap-4 md:grid-cols-2">
            <NumberField
              label="Minimum cancellation notice (days)"
              value={form.cancellation_minimum_notice_days}
              onChange={(value) => setForm((prev) => ({ ...prev, cancellation_minimum_notice_days: value }))}
            />
            <NumberField
              label="Cancellation fee ($)"
              value={form.cancellation_fee_dollars}
              step="0.01"
              onChange={(value) => setForm((prev) => ({ ...prev, cancellation_fee_dollars: value }))}
            />
          </div>
          <label className="mt-4 grid gap-1.5 text-sm font-medium text-rally-ink">
            Effective timing
            <select
              className="h-10 rounded-md border border-rally-line bg-white px-3 text-sm outline-none focus:border-blue-500"
              value={form.cancellation_effective_timing}
              onChange={(e) =>
                setForm((prev) => ({
                  ...prev,
                  cancellation_effective_timing: e.target.value as "immediate" | "end_of_period",
                }))
              }
            >
              <option value="immediate">Immediate</option>
              <option value="end_of_period">End of billing period</option>
            </select>
          </label>

          <Footer
            dirty={dirty}
            pending={mutation.isPending}
            saved={saved}
            error={mutation.isError ? mutation.error : null}
            onSave={() => mutation.mutate()}
          />
        </Card>
      )}
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
