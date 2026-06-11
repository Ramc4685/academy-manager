"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getAdminAcademy,
  updateAdminAcademy,
  type AdminAcademyView,
  type UpdateAdminAcademyRequest,
} from "@/lib/api/admin";
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
    timezone: data?.timezone ?? "UTC",
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

const TIMEZONE_OPTIONS: { group: string; zones: { value: string; label: string }[] }[] = [
  {
    group: "UTC",
    zones: [{ value: "UTC", label: "UTC" }],
  },
  {
    group: "United States & Canada",
    zones: [
      { value: "America/New_York", label: "Eastern Time — New York (ET)" },
      { value: "America/Chicago", label: "Central Time — Chicago (CT)" },
      { value: "America/Denver", label: "Mountain Time — Denver (MT)" },
      { value: "America/Phoenix", label: "Mountain Time — Phoenix (no DST)" },
      { value: "America/Los_Angeles", label: "Pacific Time — Los Angeles (PT)" },
      { value: "America/Anchorage", label: "Alaska Time (AKT)" },
      { value: "Pacific/Honolulu", label: "Hawaii Time (HST)" },
      { value: "America/Puerto_Rico", label: "Atlantic Time — Puerto Rico (AST)" },
      { value: "America/Toronto", label: "Eastern Time — Toronto (ET)" },
      { value: "America/Vancouver", label: "Pacific Time — Vancouver (PT)" },
    ],
  },
  {
    group: "Latin America",
    zones: [
      { value: "America/Mexico_City", label: "Mexico City (CST)" },
      { value: "America/Bogota", label: "Colombia Time (COT)" },
      { value: "America/Lima", label: "Peru Time (PET)" },
      { value: "America/Santiago", label: "Chile Time (CLT)" },
      { value: "America/Sao_Paulo", label: "Brasília Time (BRT)" },
      { value: "America/Argentina/Buenos_Aires", label: "Argentina Time (ART)" },
    ],
  },
  {
    group: "Europe",
    zones: [
      { value: "Europe/London", label: "London (GMT/BST)" },
      { value: "Europe/Dublin", label: "Dublin (GMT/IST)" },
      { value: "Europe/Lisbon", label: "Lisbon (WET/WEST)" },
      { value: "Europe/Paris", label: "Paris (CET/CEST)" },
      { value: "Europe/Berlin", label: "Berlin (CET/CEST)" },
      { value: "Europe/Amsterdam", label: "Amsterdam (CET/CEST)" },
      { value: "Europe/Madrid", label: "Madrid (CET/CEST)" },
      { value: "Europe/Rome", label: "Rome (CET/CEST)" },
      { value: "Europe/Stockholm", label: "Stockholm (CET/CEST)" },
      { value: "Europe/Helsinki", label: "Helsinki (EET/EEST)" },
      { value: "Europe/Athens", label: "Athens (EET/EEST)" },
      { value: "Europe/Moscow", label: "Moscow (MSK)" },
      { value: "Europe/Istanbul", label: "Istanbul (TRT)" },
    ],
  },
  {
    group: "Africa & Middle East",
    zones: [
      { value: "Africa/Cairo", label: "Cairo (EET)" },
      { value: "Africa/Johannesburg", label: "Johannesburg (SAST)" },
      { value: "Africa/Nairobi", label: "Nairobi (EAT)" },
      { value: "Asia/Dubai", label: "Dubai (GST)" },
      { value: "Asia/Riyadh", label: "Riyadh (AST)" },
    ],
  },
  {
    group: "Asia",
    zones: [
      { value: "Asia/Karachi", label: "Karachi (PKT)" },
      { value: "Asia/Kolkata", label: "India (IST)" },
      { value: "Asia/Colombo", label: "Sri Lanka (SLST)" },
      { value: "Asia/Dhaka", label: "Bangladesh (BST)" },
      { value: "Asia/Yangon", label: "Myanmar (MMT)" },
      { value: "Asia/Bangkok", label: "Bangkok (ICT)" },
      { value: "Asia/Singapore", label: "Singapore (SGT)" },
      { value: "Asia/Kuala_Lumpur", label: "Kuala Lumpur (MYT)" },
      { value: "Asia/Shanghai", label: "China Standard Time (CST)" },
      { value: "Asia/Hong_Kong", label: "Hong Kong (HKT)" },
      { value: "Asia/Taipei", label: "Taipei (CST)" },
      { value: "Asia/Tokyo", label: "Japan (JST)" },
      { value: "Asia/Seoul", label: "Korea (KST)" },
    ],
  },
  {
    group: "Australia & Pacific",
    zones: [
      { value: "Australia/Perth", label: "Perth (AWST)" },
      { value: "Australia/Darwin", label: "Darwin (ACST)" },
      { value: "Australia/Adelaide", label: "Adelaide (ACST/ACDT)" },
      { value: "Australia/Brisbane", label: "Brisbane (AEST)" },
      { value: "Australia/Sydney", label: "Sydney (AEST/AEDT)" },
      { value: "Australia/Melbourne", label: "Melbourne (AEST/AEDT)" },
      { value: "Pacific/Auckland", label: "Auckland (NZST/NZDT)" },
      { value: "Pacific/Fiji", label: "Fiji (FJT)" },
    ],
  },
];

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
  const knownValues = TIMEZONE_OPTIONS.flatMap((g) => g.zones.map((z) => z.value));
  const showUnknown = value && !knownValues.includes(value);

  return (
    <label className="grid gap-1.5 text-sm font-medium text-rally-ink">
      Timezone
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-10 rounded-md border border-rally-line bg-white px-3 text-sm font-normal outline-none focus:border-blue-500"
      >
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
