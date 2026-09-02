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

interface AcademyForm {
  display_name: string;
  timezone: string;
  contact_email: string;
  contact_phone: string;
  hours_text: string;
  address: string;
  currency: string;
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
    currency: data?.currency ?? "USD",
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
  const [form, setForm] = useState<AcademyForm>(() => normalize(null));
  const [saved, setSaved] = useState(false);

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

  const mutation = useMutation({
    mutationFn: () => updateAdminAcademy(payload),
    onSuccess: () => {
      setSaved(true);
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.academy() });
      window.setTimeout(() => setSaved(false), 2000);
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
          <CurrencySelect
            value={form.currency}
            onChange={(value) => setForm((prev) => ({ ...prev, currency: value }))}
          />
        </div>
        <PanelFooter
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

const CURRENCY_OPTIONS: { value: string; label: string }[] = [
  { value: "USD", label: "USD — US Dollar" },
  { value: "CAD", label: "CAD — Canadian Dollar" },
  { value: "EUR", label: "EUR — Euro" },
  { value: "GBP", label: "GBP — British Pound" },
  { value: "AUD", label: "AUD — Australian Dollar" },
  { value: "NZD", label: "NZD — New Zealand Dollar" },
  { value: "INR", label: "INR — Indian Rupee" },
  { value: "SGD", label: "SGD — Singapore Dollar" },
  { value: "MYR", label: "MYR — Malaysian Ringgit" },
  { value: "AED", label: "AED — UAE Dirham" },
  { value: "JPY", label: "JPY — Japanese Yen" },
  { value: "MXN", label: "MXN — Mexican Peso" },
  { value: "BRL", label: "BRL — Brazilian Real" },
  { value: "ZAR", label: "ZAR — South African Rand" },
];

function CurrencySelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const known = CURRENCY_OPTIONS.some((option) => option.value === value);
  return (
    <label className="grid gap-1.5 text-sm font-medium text-rally-ink">
      Currency
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-10 rounded-md border border-rally-line bg-white px-3 text-sm font-normal outline-none focus:border-blue-500"
      >
        {!known && value && <option value={value}>{value} (current)</option>}
        {CURRENCY_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function TimezoneSelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const showUnknown = value && !TIMEZONE_VALUES.includes(value);

  return (
    <label className="grid gap-1.5 text-sm font-medium text-rally-ink">
      Timezone
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-10 rounded-md border border-rally-line bg-white px-3 text-sm font-normal outline-none focus:border-blue-500"
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
      <Button
        variant={dirty ? "volt" : "secondary"}
        size="sm"
        disabled={!dirty || pending}
        onClick={onSave}
      >
        {pending ? "Saving..." : "Save changes"}
      </Button>
      {saved && <p className="text-sm font-medium text-emerald-700">Saved.</p>}
      {error && <p className="text-sm font-medium text-red-700">{error.message}</p>}
    </div>
  );
}
