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
import { useReportSettingsDirty } from "@/components/admin/settings/settings-dirty-context";
import { SavedNote, savedAtNow } from "@/components/admin/settings/saved-note";

interface BrandingForm {
  logo_url: string;
  brand_color: string;
  email_sender_name: string;
  email_reply_to: string;
}

export const SENDER_NAME_MAX_LENGTH = 80;

function normalize(data: AdminAcademyView | null | undefined): BrandingForm {
  return {
    logo_url: data?.logo_url ?? "",
    brand_color: data?.brand_color ?? "",
    email_sender_name: data?.email_sender_name ?? "",
    email_reply_to: data?.email_reply_to ?? "",
  };
}

/** Client-side mirror of the server rule (the server re-validates). */
export function senderNameError(value: string): string | null {
  if (/[\u0000-\u001f\u007f<>]/.test(value)) {
    return "Sender name cannot contain line breaks or angle brackets.";
  }
  if (value.trim().length > SENDER_NAME_MAX_LENGTH) {
    return `Sender name must be ${SENDER_NAME_MAX_LENGTH} characters or fewer.`;
  }
  return null;
}

function changedPayload(original: BrandingForm, form: BrandingForm): UpdateAdminAcademyRequest {
  const payload: UpdateAdminAcademyRequest = {};
  (Object.keys(form) as Array<keyof BrandingForm>).forEach((key) => {
    if (form[key] !== original[key]) {
      payload[key] = form[key].trim() === "" ? null : form[key].trim();
    }
  });
  return payload;
}

export function BrandingPanel() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<BrandingForm>(() => normalize(null));
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
  const senderPreview =
    form.email_sender_name.trim() || query.data?.display_name || "Your academy";
  useReportSettingsDirty("branding", dirty);
  const mutation = useMutation({
    mutationFn: () => updateAdminAcademy(payload),
    onSuccess: () => {
      setSavedAt(savedAtNow());
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.academy() });
    },
  });

  return (
    <section data-testid="admin-settings-branding" className="space-y-4">
      <Card p={24} className="max-w-4xl">
        <Overline>Branding</Overline>
        <div className="mt-5 grid gap-4 md:grid-cols-[1fr_180px]">
          <div className="space-y-4">
            <Field
              label="Logo URL"
              placeholder="https://..."
              value={form.logo_url}
              onChange={(value) => setForm((prev) => ({ ...prev, logo_url: value }))}
            />
            <Field
              label="Brand color"
              placeholder="#2563eb"
              value={form.brand_color}
              onChange={(value) => setForm((prev) => ({ ...prev, brand_color: value }))}
            />
          </div>
          <div className="rounded-md border border-rally-line bg-white p-4">
            <Overline>Preview</Overline>
            <div className="mt-4 flex items-center gap-3">
              <div
                className="flex h-12 w-12 items-center justify-center overflow-hidden rounded-md border border-rally-line bg-rally-paper"
                style={form.brand_color ? { borderColor: form.brand_color } : undefined}
              >
                {form.logo_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={form.logo_url} alt="" className="h-full w-full object-cover" />
                ) : (
                  <span className="font-display text-xl font-bold text-rally-ink">R</span>
                )}
              </div>
              <div>
                <div className="font-semibold text-rally-ink">Rally Academy</div>
                <div className="font-mono text-[10px] uppercase tracking-overline text-rally-muted">
                  Admin brand
                </div>
              </div>
            </div>
            <div
              className="mt-5 h-2 rounded-full bg-rally-cobalt"
              style={form.brand_color ? { backgroundColor: form.brand_color } : undefined}
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
              onChange={(value) => setForm((prev) => ({ ...prev, email_sender_name: value }))}
            />
            <Field
              id="branding-email-reply-to"
              label="Reply-to email"
              type="email"
              placeholder="frontdesk@example.com"
              value={form.email_reply_to}
              hint="Replies to academy email go here. Leave blank to keep the current behaviour."
              onChange={(value) => setForm((prev) => ({ ...prev, email_reply_to: value }))}
            />
          </div>
        </div>
        <div className="mt-6 flex flex-wrap items-center gap-3">
          <Button
            variant={dirty ? "volt" : "secondary"}
            size="sm"
            disabled={!dirty || mutation.isPending || nameError !== null}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "Saving..." : "Save branding"}
          </Button>
          <SavedNote at={savedAt} />
          {(query.isError || mutation.isError) && (
            <p role="alert" className="text-sm font-medium text-red-700">
              {(mutation.error ?? query.error)?.message}
            </p>
          )}
        </div>
      </Card>
      <Card p={20}>
        <p className="text-sm leading-6 text-rally-muted">
          Logo upload remains deferred until object storage is approved. This panel persists
          URL-based branding fields and the outbound email sender name and reply-to. Invoice and
          payment emails keep the platform sender for now.
        </p>
      </Card>
    </section>
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
  type?: "text" | "email";
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
