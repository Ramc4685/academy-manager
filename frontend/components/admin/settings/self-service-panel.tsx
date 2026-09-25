"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getSelfServicePolicy, updateSelfServicePolicy } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { isPolicyDirty, policyPatch, policyToForm, type PolicyForm } from "@/lib/self-service-policy-form";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";
import { useIsOwner } from "@/components/admin/owner-context";
import { useReportSettingsDirty } from "@/components/admin/settings/settings-dirty-context";
import { SavedNote, savedAtNow } from "@/components/admin/settings/saved-note";

export function SelfServicePanel() {
  const queryClient = useQueryClient();
  const isOwner = useIsOwner();
  const [form, setForm] = useState<PolicyForm>(() => policyToForm(null));
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const query = useQuery({
    queryKey: queryKeys.admin.selfServicePolicy(),
    queryFn: getSelfServicePolicy,
  });
  const original = useMemo(() => policyToForm(query.data), [query.data]);

  useEffect(() => {
    if (query.data) setForm(policyToForm(query.data));
  }, [query.data]);

  const dirty = isPolicyDirty(original, form);
  useReportSettingsDirty("self-service", dirty);
  // Only the changed fields are sent (money audit X5), and a blank or
  // out-of-range box is an error rather than a silent 0 (X20).
  const patch = useMemo(() => policyPatch(query.data, form), [query.data, form]);
  const hasErrors = Object.keys(patch.errors).length > 0;
  const mutation = useMutation({
    mutationFn: () => updateSelfServicePolicy(patch.payload),
    onSuccess: (data) => {
      setSavedAt(savedAtNow());
      queryClient.setQueryData(queryKeys.admin.selfServicePolicy(), data);
      // Billing rules shows the same cancellation fee and notice.
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.billingRules() });
    },
  });

  return (
    <section data-testid="admin-settings-self-service" className="space-y-6">
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
              hint="A notice filed at least this long before the class starts counts as on time."
              value={form.absence_notice_min_hours}
              error={patch.errors.absence_notice_min_hours}
              onChange={(value) => setForm((prev) => ({ ...prev, absence_notice_min_hours: value }))}
            />
            <NumberField
              label="Makeup expiry (days)"
              hint="A makeup must be requested within this many days of the missed class."
              min="1"
              value={form.makeup_expiry_days}
              error={patch.errors.makeup_expiry_days}
              onChange={(value) => setForm((prev) => ({ ...prev, makeup_expiry_days: value }))}
            />
          </div>
          <label className="mt-4 flex items-start gap-2 text-sm font-medium text-rally-ink">
            <input
              type="checkbox"
              className="mt-1"
              checked={form.makeup_requires_notice}
              onChange={(e) => setForm((prev) => ({ ...prev, makeup_requires_notice: e.target.checked }))}
            />
            <span>
              Makeup requests require an on-time absence notice
              <span className="mt-1 block text-xs font-normal text-rally-muted">
                On: a late or missing notice earns no makeup credit.
              </span>
            </span>
          </label>

          <div className="mt-8">
            <Overline>Cancellation</Overline>
          </div>
          <p className="mt-2 text-xs text-rally-muted" data-testid="self-service-cancellation-owner-note">
            {isOwner
              ? "The notice and fee are also shown in Billing rules. Changes are recorded in the billing audit log."
              : "Only the academy owner can change the cancellation notice and fee."}
          </p>
          <div className="mt-5 grid gap-4 md:grid-cols-2">
            <NumberField
              label="Minimum cancellation notice (days)"
              hint="Cancelling with less notice than this is charged the fee below."
              value={form.cancellation_minimum_notice_days}
              error={patch.errors.cancellation_minimum_notice_days}
              disabled={!isOwner}
              onChange={(value) => setForm((prev) => ({ ...prev, cancellation_minimum_notice_days: value }))}
            />
            <NumberField
              label="Cancellation fee ($)"
              hint="Flat charge to the parent when notice is short. Zero never charges."
              value={form.cancellation_fee_dollars}
              step="0.01"
              error={patch.errors.cancellation_fee_dollars}
              disabled={!isOwner}
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
            <span className="text-xs font-normal text-rally-muted">
              Immediate stops the seat and the billing now; end of period keeps both until the
              current billing period closes.
            </span>
          </label>

          <Footer
            dirty={dirty && !hasErrors}
            pending={mutation.isPending}
            savedAt={savedAt}
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
  hint,
  step = "1",
  min = "0",
  error,
  disabled = false,
  onChange,
}: {
  label: string;
  value: string;
  /** One line on what the number changes for parents — these fields move money. */
  hint?: string;
  step?: string;
  min?: string;
  error?: string;
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <label className="grid gap-1.5 text-sm font-medium text-rally-ink">
      {label}
      <input
        type="number"
        min={min}
        step={step}
        inputMode={step === "0.01" ? "decimal" : "numeric"}
        value={value}
        disabled={disabled}
        aria-invalid={error ? true : undefined}
        onChange={(event) => onChange(event.target.value)}
        className={`h-10 rounded-md border bg-white px-3 font-mono text-sm tabular-nums outline-none focus:border-blue-500 disabled:cursor-not-allowed disabled:bg-neutral-100 disabled:text-rally-muted ${
          error ? "border-red-500" : "border-rally-line"
        }`}
      />
      {error ? (
        <span className="text-xs font-normal text-red-700" role="alert">
          {error}
        </span>
      ) : (
        hint && <span className="text-xs font-normal text-rally-muted">{hint}</span>
      )}
    </label>
  );
}

function Footer({
  dirty,
  pending,
  savedAt,
  error,
  onSave,
}: {
  dirty: boolean;
  pending: boolean;
  savedAt: string | null;
  error: Error | null;
  onSave: () => void;
}) {
  return (
    <div className="mt-6 flex flex-wrap items-center gap-3">
      <Button variant={dirty ? "volt" : "secondary"} size="sm" disabled={!dirty || pending} onClick={onSave}>
        {pending ? "Saving..." : "Save changes"}
      </Button>
      <SavedNote at={savedAt} />
      {error && <p className="text-sm font-medium text-red-700">{error.message}</p>}
    </div>
  );
}
