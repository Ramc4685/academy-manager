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
import {
  SENDER_NAME_MAX_LENGTH,
  brandColorError,
  senderNameError,
} from "@/components/admin/settings/branding-panel";

/**
 * Academy profile tab (Settings overhaul Phase 3 PR 9).
 *
 * Merges the old Academy and Branding panels into one tab (key stays
 * "academy"; `?panel=branding` maps here via `RETIRED_SETTINGS_PANELS`).
 * Card order follows the settings plan: Identity, Contact & location,
 * Brand, Class defaults (new).
 */
interface AcademyForm {
  // Identity
  display_name: string;
  timezone: string;
  // Contact & location
  contact_email: string;
  contact_phone: string;
  hours_text: string;
  address: string;
  // Brand
  logo_url: string;
  brand_color: string;
  email_sender_name: string;
  email_reply_to: string;
  // Class defaults
  default_class_size: string;
  default_class_length_minutes: string;
  default_venue_address: string;
  default_parking_note: string;
  default_what_to_bring: string;
  default_arrival_minutes_before: string;
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
    logo_url: data?.logo_url ?? "",
    brand_color: data?.brand_color ?? "",
    email_sender_name: data?.email_sender_name ?? "",
    email_reply_to: data?.email_reply_to ?? "",
    default_class_size: String(data?.default_class_size ?? 10),
    default_class_length_minutes: String(data?.default_class_length_minutes ?? 45),
    default_venue_address: data?.default_venue_address ?? "",
    default_parking_note: data?.default_parking_note ?? "",
    default_what_to_bring: data?.default_what_to_bring ?? "",
    default_arrival_minutes_before: data?.default_arrival_minutes_before?.toString() ?? "",
  };
}

const TEXT_FIELDS = [
  "display_name",
  "timezone",
  "contact_email",
  "contact_phone",
  "hours_text",
  "address",
  "logo_url",
  "brand_color",
  "email_sender_name",
  "email_reply_to",
  "default_venue_address",
  "default_parking_note",
  "default_what_to_bring",
] as const satisfies ReadonlyArray<keyof AcademyForm>;

const INT_FIELDS = [
  "default_class_size",
  "default_class_length_minutes",
  "default_arrival_minutes_before",
] as const satisfies ReadonlyArray<keyof AcademyForm>;

function changedPayload(original: AcademyForm, form: AcademyForm): UpdateAdminAcademyRequest {
  const payload: UpdateAdminAcademyRequest = {};
  TEXT_FIELDS.forEach((key) => {
    if (form[key] !== original[key]) {
      payload[key] = form[key].trim() === "" ? null : form[key].trim();
    }
  });
  INT_FIELDS.forEach((key) => {
    if (form[key] !== original[key]) {
      const trimmed = form[key].trim();
      payload[key] = trimmed === "" ? null : Number.parseInt(trimmed, 10);
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
  const nameError = senderNameError(form.email_sender_name);
  const colorError = brandColorError(form.brand_color);
  const hasError = nameError !== null || colorError !== null;
  const senderPreview =
    form.email_sender_name.trim() || query.data?.display_name || "Your academy";
  const academyName = query.data?.display_name || "Your academy";
  useReportSettingsDirty("academy", dirty);

  const mutation = useMutation({
    mutationFn: () => updateAdminAcademy(payload),
    onSuccess: () => {
      setSavedAt(savedAtNow());
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.academy() });
    },
  });

  function set<K extends keyof AcademyForm>(key: K, value: string) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  return (
    <section data-testid="admin-settings-academy" aria-label="Academy profile tab" className="space-y-4">
      <Card p={24} className="max-w-4xl">
        <Overline>Identity</Overline>
        <div className="mt-5 grid gap-4 md:grid-cols-2">
          <Field label="Display name" value={form.display_name} onChange={(v) => set("display_name", v)} />
          <TimezoneSelect
            value={form.timezone}
            locked={!isOwner}
            onChange={(v) => set("timezone", v)}
          />
          <CurrencyField />
          <InvoicePrefixField prefix={query.data?.invoice_prefix ?? null} />
        </div>
      </Card>

      <Card p={24} className="max-w-4xl">
        <Overline>Contact &amp; location</Overline>
        <div className="mt-5 grid gap-4 md:grid-cols-2">
          <Field
            label="Contact email"
            type="email"
            value={form.contact_email}
            onChange={(v) => set("contact_email", v)}
          />
          <Field label="Contact phone" value={form.contact_phone} onChange={(v) => set("contact_phone", v)} />
          <Field label="Hours" value={form.hours_text} onChange={(v) => set("hours_text", v)} />
          <Field label="Address" value={form.address} onChange={(v) => set("address", v)} />
        </div>
      </Card>

      <Card p={24} className="max-w-4xl">
        <Overline>Brand</Overline>
        <div className="mt-5 grid gap-4 md:grid-cols-[1fr_180px]">
          <div className="space-y-4">
            <Field
              label="Logo URL"
              placeholder="https://..."
              value={form.logo_url}
              onChange={(v) => set("logo_url", v)}
            />
            <Field
              id="academy-brand-color"
              label="Brand colour"
              placeholder="#2563eb"
              value={form.brand_color}
              error={colorError}
              hint="A hex value like #2563EB. Leave blank to use the default."
              onChange={(v) => set("brand_color", v)}
            />
          </div>
          <div className="rounded-md border border-rally-line bg-white p-4">
            <Overline>Preview</Overline>
            <div className="mt-4 flex items-center gap-3">
              <div
                className="flex h-12 w-12 items-center justify-center overflow-hidden rounded-md border border-rally-line bg-rally-paper"
                style={form.brand_color && !colorError ? { borderColor: form.brand_color } : undefined}
              >
                {form.logo_url ? (
                  <img src={form.logo_url} alt="" className="h-full w-full object-cover" />
                ) : (
                  <span className="font-display text-xl font-bold text-rally-ink">
                    {academyName.charAt(0).toUpperCase() || "A"}
                  </span>
                )}
              </div>
              <div>
                <div className="font-semibold text-rally-ink">{academyName}</div>
                <div className="font-mono text-[10px] uppercase tracking-overline text-rally-muted">
                  Admin brand
                </div>
              </div>
            </div>
            <div
              className="mt-5 h-2 rounded-full bg-rally-cobalt"
              style={form.brand_color && !colorError ? { backgroundColor: form.brand_color } : undefined}
            />
          </div>
        </div>
        <div className="mt-6 border-t border-rally-line pt-5">
          <Overline>Outbound email</Overline>
          <div className="mt-4 grid max-w-2xl gap-4">
            <Field
              id="branding-email-sender-name"
              label="Sender name"
              placeholder={query.data?.display_name ?? "Your academy"}
              value={form.email_sender_name}
              maxLength={SENDER_NAME_MAX_LENGTH}
              error={nameError}
              hint={`Families see email from "${senderPreview}". The sending address itself stays the platform's verified address. Leave blank to use the academy name.`}
              onChange={(v) => set("email_sender_name", v)}
            />
            <Field
              id="branding-email-reply-to"
              label="Reply-to email"
              type="email"
              placeholder="frontdesk@example.com"
              value={form.email_reply_to}
              hint="Replies to academy email go here. Leave blank to keep the current behaviour."
              onChange={(v) => set("email_reply_to", v)}
            />
          </div>
        </div>
      </Card>

      <Card p={24} className="max-w-4xl">
        <Overline>Class defaults</Overline>
        <p className="mt-2 text-sm leading-6 text-rally-muted">
          What a new class starts from, and what the welcome email says when a class leaves
          these blank. Changing them here does not touch a class that already has its own
          values.
        </p>
        <div className="mt-5 grid gap-4 md:grid-cols-2">
          <Field
            label="Default class size"
            type="number"
            value={form.default_class_size}
            onChange={(v) => set("default_class_size", v)}
          />
          <Field
            label="Default class length (minutes)"
            type="number"
            value={form.default_class_length_minutes}
            onChange={(v) => set("default_class_length_minutes", v)}
          />
          <Field
            label="Default venue / address"
            value={form.default_venue_address}
            onChange={(v) => set("default_venue_address", v)}
          />
          <Field
            label="Parking note"
            value={form.default_parking_note}
            onChange={(v) => set("default_parking_note", v)}
          />
          <Field
            label="What to bring"
            value={form.default_what_to_bring}
            onChange={(v) => set("default_what_to_bring", v)}
          />
          <Field
            label="Arrive minutes early"
            type="number"
            value={form.default_arrival_minutes_before}
            onChange={(v) => set("default_arrival_minutes_before", v)}
          />
        </div>
      </Card>

      <PanelFooter
        dirty={dirty}
        pending={mutation.isPending}
        disabled={hasError}
        savedAt={savedAt}
        error={query.isError || mutation.isError ? mutation.error ?? query.error : null}
        onSave={() => mutation.mutate()}
      />
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
  id,
  label,
  value,
  onChange,
  placeholder,
  type = "text",
  maxLength,
  hint,
  error,
}: {
  id?: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: string;
  maxLength?: number;
  hint?: string;
  error?: string | null;
}) {
  const hintId = id && hint ? `${id}-hint` : undefined;
  const errorId = id && error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  return (
    <label className="grid gap-1.5 text-sm font-medium text-rally-ink">
      {label}
      <input
        id={id}
        type={type}
        value={value}
        placeholder={placeholder}
        maxLength={maxLength}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        onChange={(event) => onChange(event.target.value)}
        className="h-10 rounded-md border border-rally-line bg-white px-3 text-sm font-normal outline-none focus:border-blue-500"
      />
      {hint && (
        <span id={hintId} className="text-xs font-normal text-rally-muted">
          {hint}
        </span>
      )}
      {error && (
        <span id={errorId} role="alert" className="text-xs font-medium text-red-700">
          {error}
        </span>
      )}
    </label>
  );
}

function PanelFooter({
  dirty,
  pending,
  disabled,
  savedAt,
  error,
  onSave,
}: {
  dirty: boolean;
  pending: boolean;
  disabled: boolean;
  savedAt: string | null;
  error: Error | null;
  onSave: () => void;
}) {
  return (
    <div className="mt-2 flex flex-wrap items-center gap-3">
      <Button
        variant={dirty ? "volt" : "secondary"}
        size="sm"
        disabled={!dirty || pending || disabled}
        onClick={onSave}
      >
        {pending ? "Saving..." : "Save changes"}
      </Button>
      <SavedNote at={savedAt} />
      {error && <p className="text-sm font-medium text-red-700">{error.message}</p>}
    </div>
  );
}
