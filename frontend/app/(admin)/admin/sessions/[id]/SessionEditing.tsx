"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import {
  addSessionReplacement,
  listAdminUsers,
  setSessionAssistants,
  updateAdminSession,
  updateSessionOccurrenceReplacement,
  type AdminSessionOccurrenceView,
  type AdminSessionView,
  type AdminUserView,
  type EditSessionRequest,
} from "@/lib/api/admin";
import { roleLabel } from "@/lib/admin/role-label";
import { queryKeys } from "@/lib/query/keys";

import { Button } from "@/components/ds/button";
import {
  DialogActions,
  DialogError,
  Field,
  RallyModal as RallyDialog,
  Th,
} from "@/components/ds/dialog-chrome";

import { CoachSelect, DaySelect } from "./dialogs";
import {
  actionCellClass,
  actionHeaderClass,
  blankToNull,
  buildEditSessionForm,
  centsToDollarsInput,
  dateInputValueFromOffset,
  dollarsInputToCents,
  hasRecurringSchedule,
  inputClass,
  looksLikeWebUrl,
  looksLikeWhatsAppGroupInvite,
  sessionDateLabel,
  toDateInputValue,
  todayDateInput,
} from "./format";
import {
  parseAcademyInstant,
  resolveAcademyTimeZone,
} from "@/lib/format/academy-time";

export function ReplacementCoachTable({
  occurrences,
  userNameById,
  timezone,
  onEdit,
}: {
  occurrences: AdminSessionOccurrenceView[];
  userNameById: Map<string, string>;
  /** The parent session's IANA zone; occurrence instants render in it. */
  timezone: string | null;
  onEdit: (occurrence: AdminSessionOccurrenceView) => void;
}) {
  // Occurrence start/end are UTC instants. Formatting them without an explicit
  // timeZone renders the viewer's browser zone, which shows the wrong hour for
  // anyone outside the academy's zone.
  const { timeZone } = resolveAcademyTimeZone(timezone);
  const coachLabel = (coachId: string | null | undefined, fallback: string) =>
    coachId ? (userNameById.get(coachId) ?? fallback) : "-";

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-left text-sm">
        <thead>
          <tr className="border-b border-rally-line text-xs uppercase tracking-wide text-rally-muted">
            <Th>Date</Th>
            <Th>Time</Th>
            <Th>Scheduled coach</Th>
            <Th>Replacement coach</Th>
            <Th className={actionHeaderClass}>Action</Th>
          </tr>
        </thead>
        <tbody>
          {occurrences.map((occurrence) => (
            <tr
              key={occurrence.occurrence_id}
              className="border-b border-rally-line/60"
            >
              <td className="py-3 pr-4">
                <p className="font-medium text-rally-ink">
                  {parseAcademyInstant(occurrence.start_at).toLocaleDateString(
                    "en-US",
                    {
                      month: "short",
                      day: "numeric",
                      timeZone,
                    },
                  )}
                </p>
              </td>
              <td className="py-3 pr-4 font-mono text-rally-muted">
                {parseAcademyInstant(occurrence.start_at).toLocaleTimeString(
                  "en-US",
                  {
                    hour: "numeric",
                    minute: "2-digit",
                    timeZone,
                  },
                )}
                {" - "}
                {parseAcademyInstant(occurrence.end_at).toLocaleTimeString(
                  "en-US",
                  {
                    hour: "numeric",
                    minute: "2-digit",
                    timeZone,
                  },
                )}
              </td>
              <td className="py-3 pr-4 text-rally-muted">
                {coachLabel(occurrence.scheduled_coach_id, "Scheduled coach")}
              </td>
              <td className="py-3 pr-4 text-rally-muted">
                {coachLabel(occurrence.actual_coach_id, "Replacement coach")}
              </td>
              <td className={actionCellClass}>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => onEdit(occurrence)}
                >
                  Change replacement
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function OccurrenceReplacementDialog({
  sessionId,
  open,
  occurrence,
  onClose,
  onSaved,
}: {
  sessionId: string;
  open: boolean;
  occurrence: AdminSessionOccurrenceView | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEditing = Boolean(occurrence);
  const dialogOpen = open || isEditing;
  const [dateValue, setDateValue] = useState("");
  const [coachId, setCoachId] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const coachesQuery = useQuery({
    queryKey: queryKeys.admin.users("coach"),
    queryFn: () => listAdminUsers("coach"),
    enabled: dialogOpen,
  });
  const coaches = coachesQuery.data?.users ?? [];

  useEffect(() => {
    if (!dialogOpen) return;
    setDateValue(occurrence ? toDateInputValue(occurrence.start_at) : "");
    setCoachId(occurrence?.actual_coach_id ?? "");
    setReason("");
    setError(null);
  }, [dialogOpen, occurrence]);

  const mutation = useMutation({
    mutationFn: () => {
      const trimmedReason = reason.trim() || null;
      if (occurrence) {
        return updateSessionOccurrenceReplacement(occurrence.occurrence_id, {
          replacement_coach_id: coachId || null,
          reason: trimmedReason,
        });
      }
      return addSessionReplacement(sessionId, {
        date: dateValue,
        replacement_coach_id: coachId,
        reason: trimmedReason,
      });
    },
    onSuccess: onSaved,
    onError: (err: Error) =>
      setError(err.message ?? "Failed to update replacement coach."),
  });

  const canSave = isEditing
    ? Boolean(occurrence?.actual_coach_id || coachId)
    : Boolean(dateValue && coachId);

  return (
    <RallyDialog
      open={dialogOpen}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={isEditing ? "Change replacement" : "Add replacement"}
      description="Set the replacement coach for a normal class date."
      overline="Replacement"
    >
      {error && <DialogError message={error} />}
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          mutation.mutate();
        }}
      >
        <Field label="Date">
          <input
            type="date"
            value={dateValue}
            onChange={(event) => setDateValue(event.target.value)}
            className={inputClass}
            min={todayDateInput()}
            max={dateInputValueFromOffset(60)}
            disabled={isEditing}
          />
        </Field>
        <Field label="Replacement coach">
          {coaches.length > 0 ? (
            <CoachSelect
              coaches={coaches}
              value={coachId}
              onChange={setCoachId}
              allowEmpty={isEditing}
              emptyLabel={isEditing ? "No replacement" : "Select coach"}
            />
          ) : (
            <input
              value={coachId}
              onChange={(event) => setCoachId(event.target.value)}
              className={inputClass}
              placeholder={
                coachesQuery.isLoading
                  ? "Loading coaches..."
                  : "Coach reference"
              }
            />
          )}
        </Field>
        <Field label="Reason">
          <input
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            className={inputClass}
            placeholder="Optional"
          />
        </Field>
        <DialogActions>
          <Button variant="secondary" size="sm" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            type="submit"
            disabled={mutation.isPending || !canSave}
          >
            {mutation.isPending ? "Saving..." : "Save"}
          </Button>
        </DialogActions>
      </form>
    </RallyDialog>
  );
}

/**
 * Per-session assistant coaches. Candidates are every academy user holding
 * `coach` or `assistant_coach` (two role-filtered directory reads, merged),
 * minus the lead coach — a coach cannot assist their own session. Saves
 * through the dedicated PUT so the edit dialog's PATCH never has to carry the
 * list (there `undefined` means unchanged and `[]` clears, which is easy to
 * get wrong from a form).
 */
export function SessionAssistantsDialog({
  open,
  session,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  session: AdminSessionView | null;
  onOpenChange: (open: boolean) => void;
  onSaved: (session: AdminSessionView) => void;
}) {
  const [selected, setSelected] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const coachesQuery = useQuery({
    queryKey: queryKeys.admin.users("coach"),
    queryFn: () => listAdminUsers("coach"),
    enabled: open,
  });
  const assistantsQuery = useQuery({
    queryKey: queryKeys.admin.users("assistant_coach"),
    queryFn: () => listAdminUsers("assistant_coach"),
    enabled: open,
  });
  const loading = coachesQuery.isLoading || assistantsQuery.isLoading;

  useEffect(() => {
    if (!open || !session) return;
    setSelected([...(session.assistant_coach_ids ?? [])]);
    setReason("");
    setError(null);
  }, [open, session]);

  const candidates = useMemo(() => {
    const byId = new Map<string, AdminUserView>();
    for (const user of [
      ...(coachesQuery.data?.users ?? []),
      ...(assistantsQuery.data?.users ?? []),
    ]) {
      if (user.user_id === session?.coach_id) continue;
      if (!byId.has(user.user_id)) byId.set(user.user_id, user);
    }
    return [...byId.values()].sort((a, b) =>
      (a.display_name || a.email).localeCompare(b.display_name || b.email),
    );
  }, [coachesQuery.data, assistantsQuery.data, session?.coach_id]);

  // Assistants already on the session whose membership no longer appears in
  // the directory (role removed, account disabled) stay visible so an admin
  // can un-tick them instead of silently dropping them on save.
  const orphaned = useMemo(() => {
    const known = new Set(candidates.map((user) => user.user_id));
    const ids = session?.assistant_coach_ids ?? [];
    const names = session?.assistant_coach_names ?? [];
    return ids
      .map((assistantId, index) => ({ user_id: assistantId, label: names[index] ?? assistantId }))
      .filter((entry) => !known.has(entry.user_id));
  }, [candidates, session?.assistant_coach_ids, session?.assistant_coach_names]);

  const mutation = useMutation({
    mutationFn: () =>
      setSessionAssistants(session!.session_id, selected, reason.trim() || null),
    onSuccess: (savedSession) => {
      setError(null);
      onSaved(savedSession);
    },
    onError: (err: Error) =>
      setError(err.message || "Failed to update assistant coaches."),
  });

  const toggle = (userId: string) =>
    setSelected((prev) =>
      prev.includes(userId) ? prev.filter((id) => id !== userId) : [...prev, userId],
    );

  const optionClass =
    "flex items-start gap-3 rounded-md border border-rally-line px-3 py-2 text-sm";

  return (
    <RallyDialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) setError(null);
        onOpenChange(nextOpen);
      }}
      title="Edit assistants"
      description="Assistants see this session in their coach app and can mark attendance, update skills and add notes. They are never paid by payroll."
      overline="Coaching staff"
    >
      {error && <DialogError message={error} />}
      <form
        className="space-y-3"
        data-testid="session-assistants-form"
        onSubmit={(event) => {
          event.preventDefault();
          mutation.mutate();
        }}
      >
        <Field label="Assistant coaches">
          {loading ? (
            <p className="text-sm text-rally-subtle">Loading coaches...</p>
          ) : candidates.length === 0 && orphaned.length === 0 ? (
            <p className="text-sm text-rally-subtle" data-testid="assistant-options-empty">
              No coaches or assistant coaches to choose from. Grant the Assistant
              coach role from a user&apos;s page first.
            </p>
          ) : (
            <div className="max-h-72 space-y-2 overflow-y-auto">
              {candidates.map((user) => (
                <label key={user.user_id} className={optionClass}>
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={selected.includes(user.user_id)}
                    onChange={() => toggle(user.user_id)}
                    data-testid={`assistant-option-${user.user_id}`}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block font-medium text-rally-ink">
                      {user.display_name || user.email}
                    </span>
                    <span className="block truncate font-mono text-[11px] text-rally-muted">
                      {user.email} · {roleLabel(user.role)}
                    </span>
                  </span>
                </label>
              ))}
              {orphaned.map((entry) => (
                <label key={entry.user_id} className={optionClass}>
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={selected.includes(entry.user_id)}
                    onChange={() => toggle(entry.user_id)}
                    data-testid={`assistant-option-${entry.user_id}`}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block font-medium text-rally-ink">{entry.label}</span>
                    <span className="block text-[11px] text-amber-700">
                      No longer holds a coaching role — un-tick to remove.
                    </span>
                  </span>
                </label>
              ))}
            </div>
          )}
        </Field>
        <Field label="Reason">
          <input
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            className={inputClass}
            placeholder="Optional"
          />
        </Field>
        <DialogActions>
          <Button
            variant="secondary"
            size="sm"
            type="button"
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            type="submit"
            disabled={mutation.isPending || !session}
          >
            {mutation.isPending ? "Saving..." : "Save"}
          </Button>
        </DialogActions>
      </form>
    </RallyDialog>
  );
}

export function SessionEditDialog({
  open,
  session,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  session: AdminSessionView | null;
  onOpenChange: (open: boolean) => void;
  onSaved: (session: AdminSessionView) => void;
}) {
  const [form, setForm] = useState<EditSessionRequest>({});
  const [error, setError] = useState<string | null>(null);
  const coachesQuery = useQuery({
    queryKey: queryKeys.admin.users("coach"),
    queryFn: () => listAdminUsers("coach"),
    enabled: open,
  });
  const coaches = coachesQuery.data?.users ?? [];
  useEffect(() => {
    if (!session || !open) return;
    setForm(buildEditSessionForm(session));
  }, [open, session]);

  const recurring = session ? hasRecurringSchedule(session) : false;
  const selectedDays = form.days_of_week ?? [];

  const mutation = useMutation({
    mutationFn: (payload: EditSessionRequest) =>
      updateAdminSession(session!.session_id, payload),
    onSuccess: (savedSession) => {
      setError(null);
      onSaved(savedSession);
    },
    onError: (err: Error) =>
      setError(err.message ?? "Failed to update session."),
  });

  return (
    <RallyDialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) {
          setError(null);
          setForm({});
        }
        onOpenChange(nextOpen);
      }}
      title="Edit session"
      description="Update recurring schedule, capacity, and coach assignment."
      overline="Session"
    >
      {error && <DialogError message={error} />}
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          mutation.mutate(form);
        }}
      >
        <Field label="Coach">
          {coaches.length > 0 ? (
            <CoachSelect
              coaches={coaches}
              value={form.coach_id ?? ""}
              onChange={(coachId) =>
                setForm((f) => ({ ...f, coach_id: coachId }))
              }
            />
          ) : (
            <input
              value={form.coach_id ?? ""}
              onChange={(event) =>
                setForm((f) => ({ ...f, coach_id: event.target.value }))
              }
              className={inputClass}
              placeholder={
                coachesQuery.isLoading
                  ? "Loading coaches..."
                  : "Coach reference"
              }
            />
          )}
        </Field>
        <Field label="Name">
          <input
            value={form.title ?? ""}
            onChange={(event) =>
              setForm((f) => ({ ...f, title: event.target.value }))
            }
            className={inputClass}
          />
        </Field>
        <Field label="Location">
          <input
            value={form.location ?? ""}
            onChange={(event) =>
              setForm((f) => ({ ...f, location: event.target.value }))
            }
            className={inputClass}
          />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label={recurring ? "Day of week" : "Date"}>
            {recurring ? (
              selectedDays.length <= 1 ? (
                <DaySelect
                  value={selectedDays[0] ?? "Wed"}
                  onChange={(day) =>
                    setForm((f) => ({ ...f, days_of_week: [day] }))
                  }
                />
              ) : (
                <input
                  value={selectedDays.join(", ")}
                  readOnly
                  className={inputClass}
                />
              )
            ) : (
              <input
                value={session ? sessionDateLabel(session) : ""}
                readOnly
                className={inputClass}
              />
            )}
          </Field>
          <Field label="Start time">
            <input
              type="time"
              value={form.start_time ?? ""}
              onChange={(event) =>
                setForm((f) => ({ ...f, start_time: event.target.value }))
              }
              className={inputClass}
              disabled={!recurring}
            />
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="End time">
            <input
              type="time"
              value={form.end_time ?? ""}
              onChange={(event) =>
                setForm((f) => ({ ...f, end_time: event.target.value }))
              }
              className={inputClass}
              disabled={!recurring}
            />
          </Field>
          <Field label="Capacity">
            <input
              type="number"
              min={1}
              value={form.capacity ?? 1}
              onChange={(event) =>
                setForm((f) => ({
                  ...f,
                  capacity: parseInt(event.target.value, 10) || 1,
                }))
              }
              className={inputClass}
            />
          </Field>
        </div>
        <Field label="Monthly fee">
          <input
            type="number"
            min={0}
            step="0.01"
            value={centsToDollarsInput(form.amount_cents)}
            onChange={(event) =>
              setForm((f) => ({
                ...f,
                amount_cents: dollarsInputToCents(event.target.value),
              }))
            }
            className={inputClass}
          />
          <p className="text-xs text-amber-700">
            Percent-paid coaches require a session price for payroll. Leave
            blank only when pricing is not configured; enter 0 for an explicitly
            free session.
          </p>
        </Field>
        <CommunicationPackSection form={form} setForm={setForm} />
        <Field label="Reason">
          <input
            value={form.reason ?? ""}
            onChange={(event) =>
              setForm((f) => ({ ...f, reason: event.target.value }))
            }
            className={inputClass}
            placeholder="Optional"
          />
        </Field>
        <DialogActions>
          <Button
            variant="secondary"
            size="sm"
            type="button"
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            type="submit"
            disabled={mutation.isPending}
          >
            {mutation.isPending ? "Saving..." : "Save"}
          </Button>
        </DialogActions>
      </form>
    </RallyDialog>
  );
}

/**
 * Optional per-session onboarding facts (#613). Collapsed by default: it is a
 * long, rarely-edited block and the dialog's common job is a time or capacity
 * change. Plain controlled state and a plain button rather than a new ds
 * primitive — the design system has no accordion, and one dialog is not a
 * reason to add one.
 */
function CommunicationPackSection({
  form,
  setForm,
}: {
  form: EditSessionRequest;
  setForm: React.Dispatch<React.SetStateAction<EditSessionRequest>>;
}) {
  const [open, setOpen] = useState(false);
  const link = form.whatsapp_group_link ?? "";
  const linkLooksWrong = !looksLikeWebUrl(link);
  const linkIsNotAGroupInvite =
    link.trim() !== "" &&
    !linkLooksWrong &&
    !looksLikeWhatsAppGroupInvite(link);

  const setText = (key: keyof EditSessionRequest) => (value: string) =>
    // Empty string must become null, or clearing a box would leave the old
    // value in place (the API only clears on an explicit null).
    setForm((f) => ({ ...f, [key]: blankToNull(value) }));

  return (
    <div className="rounded-md border border-rally-line">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center justify-between px-3 py-2 text-left text-sm font-medium text-rally-ink"
      >
        <span>Communication pack (optional)</span>
        <span aria-hidden className="text-rally-muted">
          {open ? "−" : "+"}
        </span>
      </button>
      {open ? (
        <div className="space-y-3 border-t border-rally-line px-3 py-3">
          <p className="text-xs text-rally-muted">
            These details are emailed to a family when they join this session.
            Leave anything blank to keep it out of the email.
          </p>
          <Field label="WhatsApp group link">
            <input
              type="url"
              inputMode="url"
              value={link}
              onChange={(event) =>
                setText("whatsapp_group_link")(event.target.value)
              }
              className={inputClass}
              placeholder="https://chat.whatsapp.com/..."
            />
            <p className="text-xs text-rally-muted">
              In WhatsApp open the group, then Group info › Invite link › Copy
              link. It starts with https://chat.whatsapp.com/ and goes into the
              welcome email and every daily digest for this class.
            </p>
            {linkLooksWrong ? (
              <p className="text-xs text-amber-700">
                Paste the full invite link, starting with https://
              </p>
            ) : null}
            {linkIsNotAGroupInvite ? (
              <p className="text-xs text-amber-700">
                This does not look like a WhatsApp group invite
                (chat.whatsapp.com/…). A wa.me link opens a personal chat, not
                the class group.
              </p>
            ) : null}
          </Field>
          <Field label="Venue address">
            <textarea
              rows={2}
              value={form.venue_address ?? ""}
              onChange={(event) => setText("venue_address")(event.target.value)}
              className={inputClass}
            />
          </Field>
          <Field label="Parking notes">
            <textarea
              rows={2}
              value={form.parking_notes ?? ""}
              onChange={(event) => setText("parking_notes")(event.target.value)}
              className={inputClass}
            />
          </Field>
          <Field label="What to bring">
            <textarea
              rows={2}
              value={form.what_to_bring ?? ""}
              onChange={(event) => setText("what_to_bring")(event.target.value)}
              className={inputClass}
            />
          </Field>
          <Field label="Arrive N minutes before class">
            <input
              type="number"
              min={0}
              max={120}
              value={form.arrival_minutes_before ?? ""}
              onChange={(event) =>
                setForm((f) => ({
                  ...f,
                  arrival_minutes_before:
                    event.target.value.trim() === ""
                      ? null
                      : Math.max(
                          0,
                          Math.min(120, parseInt(event.target.value, 10) || 0),
                        ),
                }))
              }
              className={inputClass}
            />
          </Field>
          <Field label="Coach contact policy">
            <textarea
              rows={2}
              value={form.coach_contact_policy ?? ""}
              onChange={(event) =>
                setText("coach_contact_policy")(event.target.value)
              }
              className={inputClass}
            />
          </Field>
          <Field label="Absence & make-up policy">
            <textarea
              rows={3}
              value={form.absence_policy ?? ""}
              onChange={(event) =>
                setText("absence_policy")(event.target.value)
              }
              className={inputClass}
            />
          </Field>
        </div>
      ) : null}
    </div>
  );
}
