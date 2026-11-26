"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getAdminAiControls,
  getAdminAiWinBackPersonalised,
  getAdminNotifications,
  getCoachDigestLog,
  listAdminUsers,
  sendCoachDigestTest,
  updateAdminAiControls,
  updateAdminAiWinBackPersonalised,
  updateAdminNotifications,
  type AdminAiControlsView,
  type AdminNotificationsView,
  type CoachDigestLogEntryView,
  type CoachDigestTestSendResponse,
  type UpdateAdminAiControlsRequest,
  type UpdateAdminNotificationsRequest,
} from "@/lib/api/admin";
import { getImportSharing, setImportSharing } from "@/lib/api/admin-ai-import";
import { queryKeys } from "@/lib/query/keys";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";
import { useReportSettingsDirty } from "@/components/admin/settings/settings-dirty-context";
import { SavedNote, savedAtNow } from "@/components/admin/settings/saved-note";
import { emailFailureLabel } from "@/lib/format/email-failure";

const HOURS = Array.from({ length: 24 }, (_, h) => h);

export function normalize(
  data: Partial<AdminNotificationsView> | null | undefined
): AdminNotificationsView {
  return {
    daily_digest_to_admin: data?.daily_digest_to_admin ?? false,
    coach_digest_enabled: data?.coach_digest_enabled ?? false,
    coach_digest_hour: data?.coach_digest_hour ?? 6,
    parent_digest_enabled: data?.parent_digest_enabled ?? false,
    parent_digest_hour: data?.parent_digest_hour ?? 6,
    // On unless the academy switched it off: the backend reads it the same way.
    win_back_enabled: data?.win_back_enabled ?? true,
    trial_nudges_enabled: data?.trial_nudges_enabled ?? true,
  };
}

export function toPayload(
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
  const [savedAt, setSavedAt] = useState<string | null>(null);
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
  useReportSettingsDirty("notify", dirty);
  const mutation = useMutation({
    meta: { success: "Notification settings saved" },
    mutationFn: () => updateAdminNotifications(payload),
    onSuccess: () => {
      setSavedAt(savedAtNow());
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.notifications() });
    },
  });

  return (
    <section data-testid="admin-settings-notify">
      <Card p={24} className="max-w-3xl">
        <Overline>Notifications</Overline>
        <div className="mt-5 grid gap-3">
          {/* Issue #774: the "Dues reminders" toggle used to live here. It was
              persisted and read by nothing. The real control is Billing rules
              → Payment reminder days, where an empty list is the off switch. */}
          <p className="text-sm text-rally-muted" data-testid="notify-dues-reminders-moved">
            Payment reminder emails are configured in Settings &rarr; Billing rules.
          </p>
          <Toggle
            label="Win-back emails (30/60/90 days after leaving)"
            testId="notify-win-back-enabled"
            checked={form.win_back_enabled}
            onChange={(checked) =>
              setForm((prev) => ({ ...prev, win_back_enabled: checked }))
            }
          />
          <AiWinBackToggle />
          <Toggle
            label="Trial nudges"
            helper="Trial reminder the day before, a follow-up after a missed trial, and a reminder to finish an abandoned registration."
            testId="notify-trial-nudges-enabled"
            checked={form.trial_nudges_enabled}
            onChange={(checked) =>
              setForm((prev) => ({ ...prev, trial_nudges_enabled: checked }))
            }
          />
          <Toggle
            label="CC admins on coach digests"
            helper="Admins get a copy of each coach's daily digest email. Needs the coach daily digest turned on."
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
          <SavedNote at={savedAt} />
          {(query.isError || mutation.isError) && (
            <p className="text-sm font-medium text-red-700">
              {(mutation.error ?? query.error)?.message}
            </p>
          )}
        </div>

        <AiImportSharingToggle />
        <AiLimitsControls />
        <CoachDigestTools />
      </Card>
    </section>
  );
}

const AI_WIN_BACK_KEY = ["admin", "ai", "win-back-personalised"] as const;

/** B6: the owner's standing approval. Owner-only route, so an admin (404) sees nothing. Saves on tap. */
function AiWinBackToggle() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: AI_WIN_BACK_KEY,
    queryFn: getAdminAiWinBackPersonalised,
    retry: false,
  });
  const mutation = useMutation({
    mutationFn: (enabled: boolean) => updateAdminAiWinBackPersonalised(enabled),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: AI_WIN_BACK_KEY }),
  });
  if (!query.data) return null;
  return (
    <Toggle
      label="Personalise win-back emails with AI (uses the child's level and recent wins; you approve this wording in advance by turning it on)"
      helper={mutation.isError ? "Couldn't save that. Try again." : undefined}
      testId="notify-ai-win-back-personalised"
      checked={query.data.enabled}
      onChange={(checked) => mutation.mutate(checked)}
    />
  );
}

/**
 * Phase 2 slice B2, owner-only (`ai.share_import_values`). The GET 404s for a
 * plain admin, so the control renders for owners only; saved on change.
 */
function AiImportSharingToggle() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: queryKeys.admin.aiImportSharing(),
    queryFn: getImportSharing,
    retry: false,
  });
  const mutation = useMutation({
    mutationFn: (value: boolean) => setImportSharing(value),
    onSuccess: (view) => queryClient.setQueryData(queryKeys.admin.aiImportSharing(), view),
  });
  if (!query.data) return null;
  return (
    <div className="mt-8 border-t border-rally-line pt-6" data-testid="admin-settings-ai-import-sharing">
      <Overline>AI import helper</Overline>
      <div className="mt-4">
        <Toggle
          label="Let the AI import helper see real spreadsheet values (names, emails, phones)."
          helper="Off: it sees only the column headers and masked samples."
          testId="ai-import-share-values"
          checked={query.data.share_values}
          onChange={(checked) => mutation.mutate(checked)}
        />
        {mutation.isError && (
          <p className="mt-2 text-sm font-medium text-red-700">{mutation.error.message}</p>
        )}
      </div>
    </div>
  );
}

const AI_FEATURE_LABELS: Record<string, string> = {
  win_back_note: "Win-back email paragraph",
  technique_observation: "Coach technique notes",
  class_report: "After-class report reading",
  progress_narrative: "Progress notes for parents",
  month_close_narrator: "Month-close summary",
  pipeline_reply: "Inquiry reply drafts",
  roster_import_map: "Roster import helper",
  skill_ladder: "Skill ladder drafts",
};

export interface AiLimitsForm {
  monthly: string;
  /** feature -> text in the box; blank means no daily limit. */
  daily: Record<string, string>;
  coachReview: boolean;
}

export function aiLimitsForm(view: AdminAiControlsView): AiLimitsForm {
  return {
    monthly: String(view.monthly_call_cap),
    daily: Object.fromEntries(
      view.features.map((f) => [f, f in view.daily_call_caps ? String(view.daily_call_caps[f]) : ""])
    ),
    coachReview: view.coach_review_narratives,
  };
}

/** The request body, or an error message when a box does not hold a whole number in range. */
export function aiLimitsPayload(
  form: AiLimitsForm
): UpdateAdminAiControlsRequest | { error: string } {
  const whole = (text: string, max: number) =>
    /^\d+$/.test(text.trim()) && Number(text) <= max ? Number(text) : null;
  const monthly = whole(form.monthly, 5000);
  if (monthly === null) return { error: "Monthly limit must be a whole number from 0 to 5000." };
  const daily: Record<string, number> = {};
  for (const [feature, text] of Object.entries(form.daily)) {
    if (text.trim() === "") continue;
    const value = whole(text, 1000);
    if (value === null) return { error: "Daily limits must be blank or a whole number from 0 to 1000." };
    daily[feature] = value;
  }
  return {
    monthly_call_cap: monthly,
    daily_call_caps: daily,
    coach_review_narratives: form.coachReview,
  };
}

/**
 * L13, owner-only (`/admin/ai/controls`): the academy's AI call limits and
 * whether coaches review AI progress notes. The GET 404s for a plain admin,
 * so this renders for owners only. Every save is in the audit log.
 */
function AiLimitsControls() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: queryKeys.admin.aiControls(),
    queryFn: getAdminAiControls,
    retry: false,
  });
  const [form, setForm] = useState<AiLimitsForm | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  useEffect(() => {
    // A malformed answer hides the card instead of crashing the Notifications panel.
    if (query.data && Array.isArray(query.data.features)) setForm(aiLimitsForm(query.data));
  }, [query.data]);
  const payload = form ? aiLimitsPayload(form) : null;
  const mutation = useMutation({
    mutationFn: (body: UpdateAdminAiControlsRequest) => updateAdminAiControls(body),
    onSuccess: (view) => {
      queryClient.setQueryData(queryKeys.admin.aiControls(), view);
      setSavedAt(savedAtNow());
    },
  });
  if (!query.data || !Array.isArray(query.data.features) || !form) return null;
  const dirty = JSON.stringify(form) !== JSON.stringify(aiLimitsForm(query.data));
  const invalid = payload && "error" in payload ? payload.error : null;
  return (
    <div className="mt-8 border-t border-rally-line pt-6" data-testid="admin-settings-ai-limits">
      <Overline>AI limits</Overline>
      <p className="mt-2 text-sm leading-6 text-rally-muted">
        A ceiling on AI drafts per month for the whole academy, and optional daily limits per
        feature so one busy feature cannot use up the month. Months and days reset in UTC.
      </p>
      <label className="mt-4 grid max-w-xs gap-1.5 text-sm font-medium text-rally-ink">
        AI drafts per month
        <input
          type="number"
          inputMode="numeric"
          min={0}
          max={5000}
          value={form.monthly}
          data-testid="ai-limits-monthly"
          onChange={(event) => setForm({ ...form, monthly: event.target.value })}
          className="h-10 rounded-md border border-rally-line bg-white px-3 text-sm font-normal outline-none focus:border-blue-500"
        />
      </label>
      <fieldset className="mt-5">
        <legend className="text-sm font-medium text-rally-ink">
          Daily limit per feature (blank means no daily limit)
        </legend>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {query.data.features.map((feature) => (
            <label
              key={feature}
              className="flex items-center justify-between gap-3 text-sm text-rally-ink"
            >
              <span>{AI_FEATURE_LABELS[feature] ?? feature}</span>
              <input
                type="number"
                inputMode="numeric"
                min={0}
                max={1000}
                value={form.daily[feature] ?? ""}
                aria-label={`Daily limit: ${AI_FEATURE_LABELS[feature] ?? feature}`}
                data-testid={`ai-limits-daily-${feature}`}
                onChange={(event) =>
                  setForm({ ...form, daily: { ...form.daily, [feature]: event.target.value } })
                }
                className="h-10 w-24 rounded-md border border-rally-line bg-white px-3 text-sm outline-none focus:border-blue-500"
              />
            </label>
          ))}
        </div>
      </fieldset>
      <div className="mt-5">
        <Toggle
          label="Coaches review AI progress notes before parents see them"
          helper={
            form.coachReview
              ? undefined
              : "Off: AI-written notes go to parents with no one reading them first."
          }
          testId="ai-limits-coach-review"
          checked={form.coachReview}
          onChange={(checked) => setForm({ ...form, coachReview: checked })}
        />
      </div>
      <div className="mt-5 flex flex-wrap items-center gap-3">
        <Button
          variant={dirty ? "volt" : "secondary"}
          size="sm"
          disabled={!dirty || !!invalid || mutation.isPending}
          onClick={() => payload && !("error" in payload) && mutation.mutate(payload)}
        >
          {mutation.isPending ? "Saving..." : "Save AI limits"}
        </Button>
        <SavedNote at={savedAt} />
        {(invalid || mutation.isError) && (
          <p role="alert" className="text-sm font-medium text-red-700">
            {invalid ?? mutation.error?.message}
          </p>
        )}
      </div>
    </div>
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
    return res.detail ?? "Nothing to send — no classes today.";
  return `Test digest failed to send: ${emailFailureLabel(res.detail)}.`;
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
  testId,
  helper,
}: {
  label: string;
  helper?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  testId?: string;
}) {
  return (
    <label className="flex min-h-12 items-center justify-between gap-4 rounded-md border border-rally-line px-4 text-sm font-medium text-rally-ink">
      <span>
        {label}
        {helper && (
          <span className="mt-0.5 block text-xs font-normal text-rally-muted">{helper}</span>
        )}
      </span>
      <input
        type="checkbox"
        checked={checked}
        data-testid={testId}
        onChange={(event) => onChange(event.target.checked)}
        className="size-4 accent-blue-600"
      />
    </label>
  );
}
