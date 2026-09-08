"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getAdminNotifications,
  getCoachDigestLog,
  listAdminUsers,
  sendCoachDigestTest,
  updateAdminNotifications,
  type AdminNotificationsView,
  type CoachDigestLogEntryView,
  type CoachDigestTestSendResponse,
  type UpdateAdminNotificationsRequest,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";

const HOURS = Array.from({ length: 24 }, (_, h) => h);

function normalize(data: AdminNotificationsView | null | undefined): AdminNotificationsView {
  return {
    dues_reminders: data?.dues_reminders ?? false,
    attendance_alerts: data?.attendance_alerts ?? false,
    daily_digest_to_admin: data?.daily_digest_to_admin ?? false,
    coach_digest_enabled: data?.coach_digest_enabled ?? false,
    coach_digest_hour: data?.coach_digest_hour ?? 6,
    parent_digest_enabled: data?.parent_digest_enabled ?? false,
    parent_digest_hour: data?.parent_digest_hour ?? 6,
  };
}

function toPayload(
  original: AdminNotificationsView,
  form: AdminNotificationsView
): UpdateAdminNotificationsRequest {
  const payload: UpdateAdminNotificationsRequest = {};
  (Object.keys(form) as Array<keyof AdminNotificationsView>).forEach((key) => {
    if (form[key] !== original[key]) {
      // Index assignment is safe: keys come from the same shape.
      (payload as Record<string, unknown>)[key] = form[key];
    }
  });
  return payload;
}

function formatHour(hour: number): string {
  const h = ((hour % 24) + 24) % 24;
  const suffix = h < 12 ? "AM" : "PM";
  const display = h % 12 === 0 ? 12 : h % 12;
  return `${display}:00 ${suffix}`;
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
          <Toggle
            label="Coach daily digest"
            checked={form.coach_digest_enabled}
            onChange={(checked) =>
              setForm((prev) => ({ ...prev, coach_digest_enabled: checked }))
            }
          />
          <label className="flex min-h-12 items-center justify-between gap-4 rounded-md border border-rally-line px-4 text-sm font-medium text-rally-ink">
            Coach digest send time
            <select
              data-testid="coach-digest-hour"
              value={form.coach_digest_hour}
              disabled={!form.coach_digest_enabled}
              onChange={(event) =>
                setForm((prev) => ({
                  ...prev,
                  coach_digest_hour: Number(event.target.value),
                }))
              }
              className="rounded-md border border-rally-line bg-white px-2 py-1 text-sm disabled:opacity-50"
            >
              {HOURS.map((h) => (
                <option key={h} value={h}>
                  {formatHour(h)}
                </option>
              ))}
            </select>
          </label>
          <Toggle
            label="Parent daily digest"
            checked={form.parent_digest_enabled}
            onChange={(checked) =>
              setForm((prev) => ({ ...prev, parent_digest_enabled: checked }))
            }
          />
          <label className="flex min-h-12 items-center justify-between gap-4 rounded-md border border-rally-line px-4 text-sm font-medium text-rally-ink">
            Parent digest send time
            <select
              data-testid="parent-digest-hour"
              value={form.parent_digest_hour}
              disabled={!form.parent_digest_enabled}
              onChange={(event) =>
                setForm((prev) => ({
                  ...prev,
                  parent_digest_hour: Number(event.target.value),
                }))
              }
              className="rounded-md border border-rally-line bg-white px-2 py-1 text-sm disabled:opacity-50"
            >
              {HOURS.map((h) => (
                <option key={h} value={h}>
                  {formatHour(h)}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className="mt-2 text-xs text-rally-ink/60">
          Send time is interpreted in the server timezone.
        </p>
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

        <CoachDigestTools />
      </Card>
    </section>
  );
}

function CoachDigestTools() {
  const [coachId, setCoachId] = useState<string>("self");
  const [testDate, setTestDate] = useState<string>(() => dateInputValue(new Date()));
  const [testDateTouched, setTestDateTouched] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);

  const coaches = useQuery({
    queryKey: queryKeys.admin.users("coach"),
    queryFn: () => listAdminUsers("coach"),
  });

  const log = useQuery({
    queryKey: queryKeys.admin.coachDigestLog(),
    queryFn: () => getCoachDigestLog(10),
  });

  const testSend = useMutation({
    mutationFn: () =>
      sendCoachDigestTest({
        coach_id: coachId === "self" ? null : coachId,
        ...(testDateTouched && testDate ? { on_date: testDate } : {}),
      }),
    onSuccess: (res: CoachDigestTestSendResponse) => {
      setFeedback(describeTestResult(res));
      void log.refetch();
    },
    onError: (err: Error) => setFeedback(err.message),
  });

  const entries = log.data?.entries ?? [];
  const lastSent = entries.find((e) => e.status === "sent");

  return (
    <div className="mt-8 border-t border-rally-line pt-6">
      <Overline>Coach digest delivery</Overline>

      <div className="mt-4 flex flex-wrap items-end gap-3">
        <label className="text-sm font-medium text-rally-ink">
          Send a test to
          <select
            data-testid="coach-digest-test-target"
            value={coachId}
            onChange={(event) => setCoachId(event.target.value)}
            className="ml-2 rounded-md border border-rally-line bg-white px-2 py-1 text-sm"
          >
            <option value="self">Myself</option>
            {(coaches.data?.users ?? []).map((u) => (
              <option key={u.user_id} value={u.user_id}>
                {u.display_name || u.email}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm font-medium text-rally-ink">
          Date
          <input
            data-testid="coach-digest-test-date"
            type="date"
            value={testDate}
            onChange={(event) => {
              setTestDateTouched(true);
              setTestDate(event.target.value);
            }}
            className="ml-2 rounded-md border border-rally-line bg-white px-2 py-1 text-sm"
          />
        </label>
        <Button
          variant="secondary"
          size="sm"
          disabled={testSend.isPending}
          onClick={() => {
            setFeedback(null);
            testSend.mutate();
          }}
        >
          {testSend.isPending ? "Sending..." : "Send test digest"}
        </Button>
        {feedback && <p className="text-sm font-medium text-rally-ink">{feedback}</p>}
      </div>

      <p className="mt-4 text-sm text-rally-ink/70">
        {lastSent
          ? `Last sent ${lastSent.digest_date} to ${lastSent.coach_email ?? lastSent.coach_id}`
          : "No digests sent yet."}
      </p>

      {entries.length > 0 && (
        <div className="overflow-x-auto">
          <table className="mt-3 w-full text-left text-sm" data-testid="coach-digest-log">
            <thead>
              <tr className="text-rally-ink/60">
                <th className="py-1 pr-4 font-medium">Date</th>
                <th className="py-1 pr-4 font-medium">Coach</th>
                <th className="py-1 pr-4 font-medium">Kind</th>
                <th className="py-1 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <DigestLogRow key={entry.digest_id} entry={entry} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function DigestLogRow({ entry }: { entry: CoachDigestLogEntryView }) {
  return (
    <tr className="border-t border-rally-line/60">
      <td className="py-1 pr-4">{entry.digest_date}</td>
      <td className="py-1 pr-4">{entry.coach_email ?? entry.coach_id}</td>
      <td className="py-1 pr-4">{entry.kind}</td>
      <td className="py-1">
        <span className={statusClass(entry.status)}>{statusLabel(entry.status)}</span>
      </td>
    </tr>
  );
}

function describeTestResult(res: CoachDigestTestSendResponse): string {
  if (res.status === "sent") return `Test digest sent to ${res.email ?? res.coach_id}.`;
  if (res.status === "skipped_empty")
    return res.detail ?? "Nothing to send — no sessions for today.";
  return res.detail ?? "Test digest failed to send.";
}

function statusLabel(status: string): string {
  switch (status) {
    case "sent":
      return "Sent";
    case "skipped_empty":
      return "Skipped (empty)";
    case "failed":
      return "Failed";
    case "queued":
      return "Queued";
    default:
      return status;
  }
}

function statusClass(status: string): string {
  switch (status) {
    case "sent":
      return "font-medium text-emerald-700";
    case "failed":
      return "font-medium text-red-700";
    default:
      return "font-medium text-rally-ink/70";
  }
}

function dateInputValue(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
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
