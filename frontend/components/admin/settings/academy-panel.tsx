"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getAdminAcademy,
  updateAdminAcademy,
  type AdminAcademyView,
  type UpdateAdminAcademyRequest,
} from "@/lib/api/admin";
import { TIMEZONE_OPTIONS, TIMEZONE_VALUES } from "@/lib/format/timezone-options";
import { queryKeys } from "@/lib/query/keys";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";
import { OwnerOnlyFieldNote, useIsOwner } from "@/components/admin/owner-context";
import { useReportSettingsDirty } from "@/components/admin/settings/settings-dirty-context";
import { SavedNote, savedAtNow } from "@/components/admin/settings/saved-note";

interface AcademyForm {
  display_name: string;
  timezone: string;
  contact_email: string;
  contact_phone: string;
  hours_text: string;
  address: string;
}

function normalize(data: AdminAcademyView | null | undefined): AcademyForm {
  return {
    display_name: data?.display_name ?? "",
    // NOT "UTC": the backend now returns null for an academy that has never
    // had a timezone chosen, and substituting UTC here would make the panel
    // claim a zone the tenant never picked — then save it on the next edit.
    timezone: data?.timezone ?? "",
    contact_email: data?.contact_email ?? "",
    contact_phone: data?.contact_phone ?? "",
    hours_text: data?.hours_text ?? "",
    address: data?.address ?? "",
  };
}

function changedPayload(original: AcademyForm, form: AcademyForm): UpdateAdminAcademyRequest {
  const payload: UpdateAdminAcademyRequest = {};
  (Object.keys(form) as Array<keyof AcademyForm>).forEach((key) => {
    if (form[key] !== original[key]) {
      payload[key] = form[key].trim() === "" ? null : form[key];
    }
  });
  return payload;
}

export function AcademyPanel() {
  const queryClient = useQueryClient();
  // Timezone and currency decide when a billing month starts and what unit
  // every price is in, so they are owner-only (Settings overhaul P1 PR 5).
  const isOwner = useIsOwner();
  const [form, setForm] = useState<AcademyForm>(() => normalize(null));
  const [savedAt, setSavedAt] = useState<string | null>(null);

  const query = useQuery({
    queryKey: queryKeys.admin.academy(),
    queryFn: getAdminAcademy,
  });

  const original = useMemo(() => normalize(query.data), [query.data]);
  useEffect(() => {
    if (query.data) setForm(normalize(query.data));
  }, [query.data]);

  const payload = changedPayload(original, form);
  const dirty = Object.keys(payload).length > 0;
  useReportSettingsDirty("academy", dirty);

  const mutation = useMutation({
    mutationFn: () => updateAdminAcademy(payload),
    onSuccess: () => {
      setSavedAt(savedAtNow());
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.academy() });
    },
  });

  return (
    <section data-testid="admin-settings-academy">
      <Card p={24} className="max-w-4xl">
        <Overline>Academy</Overline>
        <div className="mt-5 grid gap-4 md:grid-cols-2">
          <Field
            label="Display name"
            value={form.display_name}
            onChange={(value) => setForm((prev) => ({ ...prev, display_name: value }))}
          />
          <TimezoneSelect
            value={form.timezone}
            locked={!isOwner}
            onChange={(value) => setForm((prev) => ({ ...prev, timezone: value }))}
          />
          <Field
            label="Contact email"
            type="email"
            value={form.contact_email}
            onChange={(value) => setForm((prev) => ({ ...prev, contact_email: value }))}
          />
          <Field
            label="Contact phone"
            value={form.contact_phone}
            onChange={(value) => setForm((prev) => ({ ...prev, contact_phone: value }))}
          />
          <Field
            label="Hours"
            value={form.hours_text}
            onChange={(value) => setForm((prev) => ({ ...prev, hours_text: value }))}
          />
          <Field
            label="Address"
            value={form.address}
            onChange={(value) => setForm((prev) => ({ ...prev, address: value }))}
          />
          <CurrencyField />
          <InvoicePrefixField prefix={query.data?.invoice_prefix ?? null} />
        </div>
        <PanelFooter
          dirty={dirty}
          pending={mutation.isPending}
          savedAt={savedAt}
          error={query.isError || mutation.isError ? mutation.error ?? query.error : null}
          onSave={() => mutation.mutate()}
        />
      </Card>
    </section>
  );
}

/** Helper text under the read-only invoice prefix. */
export function invoicePrefixHint(prefix: string | null): string {
  if (!prefix) {
    return "Not set yet. CourtMastr sets it before your first invoice.";
  }
  return `Invoice numbers look like ${prefix}-2026-09-0001. Set by CourtMastr.`;
}

function InvoicePrefixField({ prefix }: { prefix: string | null }) {
  // Read-only: the platform sets the prefix per academy and locks it after
  // the first numbered invoice, so it has no place in the save payload.
  return (
    <div className="grid gap-1.5 text-sm font-medium text-rally-ink">
      <span id="academy-invoice-prefix-label">Invoice prefix</span>
      <input
        aria-labelledby="academy-invoice-prefix-label"
        aria-describedby="academy-invoice-prefix-hint"
        data-testid="academy-invoice-prefix"
        value={prefix ?? ""}
        placeholder="Not set"
        readOnly
        className="h-10 rounded-md border border-rally-line bg-rally-paper px-3 font-mono text-sm font-normal text-rally-muted outline-none"
      />
      <span id="academy-invoice-prefix-hint" className="text-xs font-normal text-rally-muted">
        {invoicePrefixHint(prefix)}
      </span>
    </div>
  );
}

const LOCKABLE_SELECT_CLASS =
  "h-10 rounded-md border border-rally-line bg-white px-3 text-sm font-normal outline-none focus:border-blue-500 disabled:cursor-not-allowed disabled:bg-neutral-100 disabled:text-rally-muted";

/**
 * Currency is locked to USD (owner decision, Settings overhaul Phase 1 PR 3).
 * Read-only here; the admin update payload never sends a currency.
 */
function CurrencyField() {
  return (
    <div className="grid gap-1.5 text-sm font-medium text-rally-ink">
      <span id="academy-currency-label">Currency</span>
      <input
        aria-labelledby="academy-currency-label"
        aria-describedby="academy-currency-hint"
        data-testid="academy-currency"
        value="USD"
        readOnly
        className="h-10 rounded-md border border-rally-line bg-rally-paper px-3 text-sm font-normal text-rally-muted outline-none"
      />
      <span id="academy-currency-hint" className="text-xs font-normal text-rally-muted">
        Set by CourtMastr. All charges are in US dollars.
      </span>
    </div>
  );
}

export function TimezoneSelect({
  value,
  onChange,
  locked = false,
}: {
  value: string;
  onChange: (value: string) => void;
  /** True for an admin without the owner scope: shown, not editable. */
  locked?: boolean;
}) {
  const showUnknown = value && !TIMEZONE_VALUES.includes(value);

  return (
    <label className="grid gap-1.5 text-sm font-medium text-rally-ink">
      Timezone
      <select
        value={value}
        disabled={locked}
        aria-describedby={locked ? "academy-timezone-owner-note" : undefined}
        onChange={(e) => onChange(e.target.value)}
        className={LOCKABLE_SELECT_CLASS}
      >
        {/* An academy with no stored timezone must READ as unset, not as
            "UTC". Defaulting the control to UTC is what let a Chicago academy
            be saved as a UTC academy without anyone choosing it. */}
        {!value && (
          <option value="" disabled>
            Select a timezone…
          </option>
        )}
        {showUnknown && (
          <option value={value}>{value} (current)</option>
        )}
        {TIMEZONE_OPTIONS.map((group) => (
          <optgroup key={group.group} label={group.group}>
            {group.zones.map((zone) => (
              <option key={zone.value} value={zone.value}>
                {zone.label}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      {locked && <OwnerOnlyFieldNote id="academy-timezone-owner-note" />}
    </label>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
}) {
  return (
    <label className="grid gap-1.5 text-sm font-medium text-rally-ink">
      {label}
      <input
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-10 rounded-md border border-rally-line bg-white px-3 text-sm font-normal outline-none focus:border-blue-500"
      />
    </label>
  );
}

function PanelFooter({
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
      <Button
        variant={dirty ? "volt" : "secondary"}
        size="sm"
        disabled={!dirty || pending}
        onClick={onSave}
      >
        {pending ? "Saving..." : "Save changes"}
      </Button>
      <SavedNote at={savedAt} />
      {error && <p className="text-sm font-medium text-red-700">{error.message}</p>}
    </div>
  );
}
