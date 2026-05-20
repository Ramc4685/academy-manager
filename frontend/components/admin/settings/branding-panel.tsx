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

interface BrandingForm {
  logo_url: string;
  brand_color: string;
}

function normalize(data: AdminAcademyView | null | undefined): BrandingForm {
  return {
    logo_url: data?.logo_url ?? "",
    brand_color: data?.brand_color ?? "",
  };
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
        <div className="mt-6 flex flex-wrap items-center gap-3">
          <Button
            variant={dirty ? "volt" : "secondary"}
            size="sm"
            disabled={!dirty || mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "Saving..." : "Save branding"}
          </Button>
          {saved && <p className="text-sm font-medium text-emerald-700">Saved.</p>}
          {(query.isError || mutation.isError) && (
            <p role="alert" className="text-sm font-medium text-red-700">
              {(mutation.error ?? query.error)?.message}
            </p>
          )}
        </div>
      </Card>
      <Card p={20}>
        <p className="text-sm leading-6 text-rally-muted">
          Logo upload and email signature rendering remain deferred until object storage and
          outbound-email branding contracts are approved. This panel only persists URL-based
          branding fields.
        </p>
      </Card>
    </section>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="grid gap-1.5 text-sm font-medium text-rally-ink">
      {label}
      <input
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="h-10 rounded-md border border-rally-line bg-white px-3 text-sm font-normal outline-none focus:border-blue-500"
      />
    </label>
  );
}
