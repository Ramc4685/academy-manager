"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getDeparturePolicy,
  updateDeparturePolicy,
  type DropDefaultOutcome,
  type EnrollmentDeparturePolicyView,
  type HoldReclaimPolicy,
} from "@/lib/api/v2/departure-policy";
import { queryKeys } from "@/lib/query/keys";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";
import { OwnerOnlyHint, useIsOwner } from "@/components/admin/owner-context";

// Structurally mirrors self-service-panel.tsx (PolicyForm -> normalize() ->
// isDirty() -> mutation payload -> inputs), but is its OWN card with its OWN
// Save button and never shares form state with the self-service panel — see
// domain/departure_policy.py §1.1(1): a shared whole-object PUT would let a
// stale self-service tab silently rewrite departure policy.
type PolicyForm = {
  max_hold_days: string;
  hold_reclaim_policy: HoldReclaimPolicy;
  drop_default_outcome: DropDefaultOutcome;
  delete_enrollment_requires_owner: boolean;
};

function normalize(data: EnrollmentDeparturePolicyView | null | undefined): PolicyForm {
  return {
    max_hold_days: data?.max_hold_days?.toString() ?? "60",
    hold_reclaim_policy: data?.hold_reclaim_policy ?? "longest_held",
    drop_default_outcome: data?.drop_default_outcome ?? "no_credit_mid_month",
    delete_enrollment_requires_owner: data?.delete_enrollment_requires_owner ?? true,
  };
}

function isDirty(original: PolicyForm, form: PolicyForm): boolean {
  return (Object.keys(form) as Array<keyof PolicyForm>).some((key) => form[key] !== original[key]);
}

export function DeparturePolicyPanel() {
  const isOwner = useIsOwner();
  const queryClient = useQueryClient();
  const [form, setForm] = useState<PolicyForm>(() => normalize(null));
  const [saved, setSaved] = useState(false);
  const query = useQuery({
    queryKey: queryKeys.admin.departurePolicy(),
    queryFn: getDeparturePolicy,
  });
  const original = useMemo(() => normalize(query.data), [query.data]);

  useEffect(() => {
    if (query.data) setForm(normalize(query.data));
  }, [query.data]);

  const dirty = isDirty(original, form);
  const mutation = useMutation({
    mutationFn: () =>
      updateDeparturePolicy({
        max_hold_days: Number(form.max_hold_days) || 60,
        hold_reclaim_policy: form.hold_reclaim_policy,
        drop_default_outcome: form.drop_default_outcome,
        delete_enrollment_requires_owner: form.delete_enrollment_requires_owner,
      }),
    onSuccess: () => {
      setSaved(true);
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.departurePolicy() });
      window.setTimeout(() => setSaved(false), 2000);
    },
  });

  const disabled = !isOwner;

  return (
    <section data-testid="admin-settings-departure-policy" className="space-y-6">
      {query.isError ? (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load departure policy.
        </p>
      ) : query.isLoading ? (
        <div className="h-48 animate-pulse rounded-xl bg-neutral-100 dark:bg-neutral-800" />
      ) : (
        <Card p={24} className="max-w-3xl">
          <div className="flex items-center justify-between">
            <Overline>Departures &amp; holds</Overline>
            {disabled && <OwnerOnlyHint />}
          </div>
          <div className="mt-5 grid gap-4 md:grid-cols-2">
            <label className="grid gap-1.5 text-sm font-medium text-rally-ink">
              Maximum hold length (days)
              <input
                type="number"
                min="1"
                max="365"
                disabled={disabled}
                value={form.max_hold_days}
                onChange={(e) => setForm((prev) => ({ ...prev, max_hold_days: e.target.value }))}
                className="h-10 rounded-md border border-rally-line bg-white px-3 font-mono text-sm tabular-nums outline-none focus:border-blue-500 disabled:opacity-60"
              />
            </label>
            <label className="grid gap-1.5 text-sm font-medium text-rally-ink">
              When a full class needs a seat
              <select
                disabled={disabled}
                className="h-10 rounded-md border border-rally-line bg-white px-3 text-sm outline-none focus:border-blue-500 disabled:opacity-60"
                value={form.hold_reclaim_policy}
                onChange={(e) =>
                  setForm((prev) => ({
                    ...prev,
                    hold_reclaim_policy: e.target.value as HoldReclaimPolicy,
                  }))
                }
              >
                <option value="longest_held">Reclaim the longest-held hold</option>
                <option value="never">Never reclaim (class stays full)</option>
              </select>
            </label>
          </div>
          <label className="mt-4 grid gap-1.5 text-sm font-medium text-rally-ink">
            Default Drop outcome
            <select
              disabled={disabled}
              className="h-10 rounded-md border border-rally-line bg-white px-3 text-sm outline-none focus:border-blue-500 disabled:opacity-60"
              value={form.drop_default_outcome}
              onChange={(e) =>
                setForm((prev) => ({
                  ...prev,
                  drop_default_outcome: e.target.value as DropDefaultOutcome,
                }))
              }
            >
              <option value="no_credit_mid_month">No credit, mid-month (default)</option>
              <option value="credit_mid_month">Prorated credit, mid-month</option>
              <option value="no_credit_end_of_period">No credit, end of period</option>
            </select>
          </label>
          <label className="mt-4 flex items-center gap-2 text-sm font-medium text-rally-ink">
            <input
              type="checkbox"
              disabled={disabled}
              checked={form.delete_enrollment_requires_owner}
              onChange={(e) =>
                setForm((prev) => ({ ...prev, delete_enrollment_requires_owner: e.target.checked }))
              }
            />
            Delete requires the academy owner
          </label>

          <div className="mt-6 flex flex-wrap items-center gap-3">
            <Button
              variant={dirty ? "volt" : "secondary"}
              size="sm"
              disabled={disabled || !dirty || mutation.isPending}
              onClick={() => mutation.mutate()}
            >
              {mutation.isPending ? "Saving..." : "Save changes"}
            </Button>
            {saved && <p className="text-sm font-medium text-emerald-700">Saved.</p>}
            {mutation.isError && (
              <p className="text-sm font-medium text-red-700">{mutation.error.message}</p>
            )}
          </div>
        </Card>
      )}
    </section>
  );
}
