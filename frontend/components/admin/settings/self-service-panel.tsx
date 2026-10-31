"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getSelfServicePolicy, updateSelfServicePolicy } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import {
  cancellationTermsSummary,
  isPolicyDirty,
  policyPatch,
  policyToForm,
  type PolicyForm,
} from "@/lib/self-service-policy-form";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";
import { useIsOwner } from "@/components/admin/owner-context";
import { useReportSettingsDirty } from "@/components/admin/settings/settings-dirty-context";
import { SavedNote, savedAtNow } from "@/components/admin/settings/saved-note";
import { WaiversManagement } from "@/components/admin/waivers/waivers-management";

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
        <>
          <Card p={24} className="max-w-3xl" data-testid="family-policies-absences-card">
            <Overline>Absences &amp; makeups</Overline>
            <div className="mt-5 grid gap-4 md:grid-cols-2">
              <NumberField
                label="Minimum absence notice (hours)"
                hint="A notice filed at least this long before the class starts counts as on time."
                value={form.absence_notice_min_hours}
                error={patch.errors.absence_notice_min_hours}
                onChange={(value) =>
                  setForm((prev) => ({ ...prev, absence_notice_min_hours: value }))
                }
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
                onChange={(e) =>
                  setForm((prev) => ({ ...prev, makeup_requires_notice: e.target.checked }))
                }
              />
              <span>
                Makeup requests require an on-time absence notice
                <span className="mt-1 block text-xs font-normal text-rally-muted">
                  On: a late or missing notice earns no makeup credit.
                </span>
              </span>
            </label>

            <label className="mt-6 grid gap-1.5 text-sm font-medium text-rally-ink">
              Welcome email absence &amp; makeup policy (default)
              <textarea
                value={form.welcome_email_absence_policy_default}
                onChange={(e) =>
                  setForm((prev) => ({
                    ...prev,
                    welcome_email_absence_policy_default: e.target.value,
                  }))
                }
                rows={3}
                placeholder="e.g. Report absences at least 2 hours before class in the parent app."
                className="min-h-[80px] rounded-md border border-rally-line bg-white px-3 py-2 text-sm outline-none focus:border-blue-500"
                data-testid="welcome-email-absence-policy-default"
              />
              <span className="text-xs font-normal text-rally-muted">
                Shown in a class&apos;s welcome email only when that class has not set its own
                absence &amp; makeup text. A class&apos;s own text always wins.
              </span>
            </label>

            <div className="mt-8">
              <Overline>Cancellation</Overline>
            </div>
            {/* The notice and fee live only in Billing rules (Settings overhaul
                P1 PR 5): owner-only there, and never written from here. */}
            <p className="mt-2 text-sm text-rally-ink" data-testid="self-service-cancellation-terms">
              {cancellationTermsSummary(query.data)}{" "}
              {isOwner ? (
                <Link
                  href="/admin/settings?panel=billing-rules"
                  className="font-medium text-rally-cobalt-700 underline underline-offset-2 hover:text-rally-cobalt-800"
                >
                  Change in Billing rules
                </Link>
              ) : (
                <span className="text-rally-muted">Only the academy owner can change them.</span>
              )}
            </p>

            {/* One shared form/mutation across this card and "What parents
                can do in the app" below — either Save button writes every
                changed field from both, in one PUT. */}
            <Footer
              dirty={dirty && !hasErrors}
              pending={mutation.isPending}
              savedAt={savedAt}
              error={mutation.isError ? mutation.error : null}
              onSave={() => mutation.mutate()}
            />
          </Card>

          <Card p={24} className="max-w-3xl" data-testid="family-policies-parent-actions-card">
            <Overline>What parents can do in the app</Overline>
            <p className="mt-2 text-xs text-rally-muted">
              Off hides the action for parents; a parent who tries anyway gets a clear message to
              contact the academy directly. Free trial requests are governed by the Public page{" "}
              <a href="?panel=public-page" className="underline">
                &quot;Accept free trial requests&quot;
              </a>{" "}
              toggle, not a switch here.
            </p>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <SwitchField
                label="Report an absence"
                checked={form.can_report_absence}
                onChange={(checked) => setForm((prev) => ({ ...prev, can_report_absence: checked }))}
              />
              <SwitchField
                label="Request a makeup"
                checked={form.can_request_makeup}
                onChange={(checked) => setForm((prev) => ({ ...prev, can_request_makeup: checked }))}
              />
              <SwitchField
                label="Request a pause / hold"
                checked={form.can_request_pause}
                onChange={(checked) => setForm((prev) => ({ ...prev, can_request_pause: checked }))}
              />
              <SwitchField
                label="Request to cancel / withdraw"
                checked={form.can_request_cancel}
                onChange={(checked) => setForm((prev) => ({ ...prev, can_request_cancel: checked }))}
              />
              <SwitchField
                label="Claim a waitlist seat offer"
                checked={form.can_claim_waitlist_offer}
                onChange={(checked) =>
                  setForm((prev) => ({ ...prev, can_claim_waitlist_offer: checked }))
                }
              />
            </div>

            <Footer
              dirty={dirty && !hasErrors}
              pending={mutation.isPending}
              savedAt={savedAt}
              error={mutation.isError ? mutation.error : null}
              onSave={() => mutation.mutate()}
            />
          </Card>

          <div data-testid="family-policies-registration-waivers-card" className="max-w-3xl space-y-4">
            <Overline>Registration &amp; waivers</Overline>
            <WaiversManagement />
          </div>

          <Card p={20} className="max-w-3xl" data-testid="family-policies-billing-link-card">
            <p className="text-sm text-rally-ink">
              Cancellation fee &amp; notice — now in{" "}
              <Link
                href="/admin/settings?panel=billing-rules"
                className="font-medium text-rally-cobalt-700 underline underline-offset-2 hover:text-rally-cobalt-800"
              >
                Billing rules
              </Link>
              .
            </p>
          </Card>
        </>
      )}
    </section>
  );
}

function SwitchField({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 text-sm font-medium text-rally-ink">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        data-testid={`self-service-switch-${label.toLowerCase().replace(/[^a-z]+/g, "-")}`}
      />
      {label}
    </label>
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
