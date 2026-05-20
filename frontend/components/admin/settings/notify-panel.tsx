"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getAdminNotifications,
  updateAdminNotifications,
  type AdminNotificationsView,
  type UpdateAdminNotificationsRequest,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";

function normalize(data: AdminNotificationsView | null | undefined): AdminNotificationsView {
  return {
    dues_reminders: data?.dues_reminders ?? false,
    attendance_alerts: data?.attendance_alerts ?? false,
    daily_digest_to_admin: data?.daily_digest_to_admin ?? false,
  };
}

function toPayload(
  original: AdminNotificationsView,
  form: AdminNotificationsView
): UpdateAdminNotificationsRequest {
  const payload: UpdateAdminNotificationsRequest = {};
  (Object.keys(form) as Array<keyof AdminNotificationsView>).forEach((key) => {
    if (form[key] !== original[key]) payload[key] = form[key];
  });
  return payload;
}

export function NotifyPanel() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<AdminNotificationsView>(() => normalize(null));
  const [saved, setSaved] = useState(false);
  const query = useQuery({
    queryKey: queryKeys.admin.notifications(),
    queryFn: getAdminNotifications,
  });
  const original = useMemo(() => normalize(query.data), [query.data]);

  useEffect(() => {
    if (query.data) setForm(normalize(query.data));
  }, [query.data]);

  const payload = toPayload(original, form);
  const dirty = Object.keys(payload).length > 0;
  const mutation = useMutation({
    mutationFn: () => updateAdminNotifications(payload),
    onSuccess: () => {
      setSaved(true);
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.notifications() });
      window.setTimeout(() => setSaved(false), 2000);
    },
  });

  return (
    <section data-testid="admin-settings-notify">
      <Card p={24} className="max-w-3xl">
        <Overline>Notifications</Overline>
        <div className="mt-5 grid gap-3">
          <Toggle
            label="Dues reminders"
            checked={form.dues_reminders}
            onChange={(checked) => setForm((prev) => ({ ...prev, dues_reminders: checked }))}
          />
          <Toggle
            label="Attendance alerts"
            checked={form.attendance_alerts}
            onChange={(checked) => setForm((prev) => ({ ...prev, attendance_alerts: checked }))}
          />
          <Toggle
            label="Daily admin digest"
            checked={form.daily_digest_to_admin}
            onChange={(checked) =>
              setForm((prev) => ({ ...prev, daily_digest_to_admin: checked }))
            }
          />
        </div>
        <div className="mt-6 flex flex-wrap items-center gap-3">
          <Button
            variant={dirty ? "volt" : "secondary"}
            size="sm"
            disabled={!dirty || mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "Saving..." : "Save changes"}
          </Button>
          {saved && <p className="text-sm font-medium text-emerald-700">Saved.</p>}
          {(query.isError || mutation.isError) && (
            <p className="text-sm font-medium text-red-700">
              {(mutation.error ?? query.error)?.message}
            </p>
          )}
        </div>
      </Card>
    </section>
  );
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex min-h-12 items-center justify-between gap-4 rounded-md border border-rally-line px-4 text-sm font-medium text-rally-ink">
      {label}
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="size-4 accent-blue-600"
      />
    </label>
  );
}
