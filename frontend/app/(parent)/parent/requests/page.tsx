"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import { Button } from "@/components/ds/button";
import { EmptyState } from "@/components/ds/empty-state";
import { queryKeys } from "@/lib/query/keys";
import { requestStatusChipVariant } from "@/lib/parent-requests";
import {
  formatAcademyDate,
  formatAcademyDateTime,
  formatAcademyTimeRange,
} from "@/lib/format/academy-time";
import {
  getChildSchedule,
  getParentAcademy,
  listAvailableParentSessions,
  listEligibleMakeupTargets,
  listParentAbsences,
  listParentChildren,
  listParentMakeups,
  listParentTrialRequests,
  submitAbsenceNotice,
  submitMakeupRequest,
  submitTrialRequest,
  type AbsenceNoticeView,
  type MakeupRequestView,
  type ParentChild,
  type ParentScheduleEntry,
  type TrialRequestStudentRef,
  type TrialRequestView,
} from "@/lib/api/parent";

type RequestTab = "absences" | "makeups" | "trials";

const TABS: { id: RequestTab; label: string }[] = [
  { id: "absences", label: "Absences" },
  { id: "makeups", label: "Makeups" },
  { id: "trials", label: "Trials" },
];

export default function ParentRequestsPage() {
  const [tab, setTab] = useState<RequestTab>("absences");

  return (
    <section data-testid="parent-requests" className="space-y-4">
      <div className="animate-fade-in-up">
        <h1 className="font-display text-2xl font-bold tracking-tight text-rally-ink">Requests</h1>
        <p className="text-sm mt-0.5 text-rally-muted">Absences, makeups &amp; trial classes</p>
      </div>

      <div role="tablist" aria-label="Request type" className="flex gap-1 rounded-xl bg-rally-line p-1">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`min-h-touch flex-1 rounded-lg text-sm font-semibold transition-all duration-150 ${
              tab === t.id
                ? "bg-white text-rally-ink shadow-[0_1px_2px_rgba(0,0,0,0.06)]"
                : "bg-transparent text-rally-muted"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "absences" && <AbsencesPanel />}
      {tab === "makeups" && <MakeupsPanel />}
      {tab === "trials" && <TrialsPanel />}
    </section>
  );
}

// --- Absences ---

function AbsencesPanel() {
  const queryClient = useQueryClient();
  const [studentId, setStudentId] = useState<string>("");
  const [occurrenceId, setOccurrenceId] = useState<string>("");
  const [lastWarning, setLastWarning] = useState<boolean | null>(null);

  const academyQuery = useQuery({
    queryKey: ["parent", "academy"],
    queryFn: getParentAcademy,
  });
  const childrenQuery = useQuery({
    queryKey: ["parent", "children"],
    queryFn: listParentChildren,
  });
  const absencesQuery = useQuery({
    queryKey: queryKeys.parent.absences(),
    queryFn: listParentAbsences,
  });
  const scheduleQuery = useQuery({
    queryKey: ["parent", "child-schedule", studentId],
    queryFn: () => getChildSchedule(studentId),
    enabled: Boolean(studentId),
  });

  const submitMutation = useMutation({
    mutationFn: submitAbsenceNotice,
    onSuccess: (notice) => {
      setLastWarning(notice.notice_window_met === false);
      setOccurrenceId("");
      void queryClient.invalidateQueries({ queryKey: queryKeys.parent.absences() });
    },
  });

  const children = childrenQuery.data?.children ?? [];
  const academyTimezone = academyQuery.data?.timezone ?? null;
  const occurrences = scheduleQuery.data?.entries ?? [];
  const notices = absencesQuery.data?.notices ?? [];

  return (
    <div className="space-y-4">
      <Card p={16}>
        <h2 className="text-sm font-bold mb-3 text-rally-ink">Report an absence</h2>

        {submitMutation.isError ? (
          <p role="alert" className="mb-3 rounded-md bg-status-red-50 p-3 text-sm text-status-red-800">
            {submitMutation.error instanceof Error
              ? submitMutation.error.message
              : "Could not submit absence notice."}
          </p>
        ) : null}
        {lastWarning === true && (
          <p role="alert" className="mb-3 rounded-md bg-status-amber-50 p-3 text-sm text-status-amber-800">
            Submitted inside the notice window — makeup eligibility may be affected.
          </p>
        )}
        {lastWarning === false && submitMutation.isSuccess ? (
          <p role="status" className="mb-3 rounded-md bg-status-green-50 p-3 text-sm text-status-green-800">
            Absence notice submitted.
          </p>
        ) : null}

        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (!studentId || !occurrenceId) return;
            setLastWarning(null);
            submitMutation.mutate({ student_id: studentId, occurrence_id: occurrenceId });
          }}
        >
          <label className="block text-xs font-semibold text-rally-muted">
            Child
            <select
              className="mt-1 min-h-touch w-full rounded-lg border border-rally-line px-3 text-sm"
              value={studentId}
              onChange={(e) => {
                setStudentId(e.target.value);
                setOccurrenceId("");
              }}
              disabled={childrenQuery.isLoading}
            >
              <option value="">Select a child</option>
              {children.map((c: ParentChild) => (
                <option key={c.student_id} value={c.student_id}>
                  {c.full_name}
                </option>
              ))}
            </select>
          </label>

          <label className="block text-xs font-semibold text-rally-muted">
            Upcoming class
            <select
              className="mt-1 min-h-touch w-full rounded-lg border border-rally-line px-3 text-sm"
              value={occurrenceId}
              onChange={(e) => setOccurrenceId(e.target.value)}
              disabled={!studentId || scheduleQuery.isLoading}
            >
              <option value="">
                {!studentId
                  ? "Select a child first"
                  : scheduleQuery.isLoading
                    ? "Loading…"
                    : occurrences.length === 0
                      ? "No upcoming classes"
                      : "Select a class"}
              </option>
              {occurrences.map((o: ParentScheduleEntry) => (
                <option key={o.occurrence_id} value={o.occurrence_id}>
                  {o.session_title} — {formatAcademyTimeRange(o.start_at, o.end_at, academyTimezone)}
                </option>
              ))}
            </select>
          </label>

          <Button
            type="submit"
            variant="primary"
            full
            disabled={!studentId || !occurrenceId || submitMutation.isPending}
          >
            {submitMutation.isPending ? "Submitting…" : "Report absence"}
          </Button>
        </form>
      </Card>

      <div>
        <h2 className="text-sm font-bold mb-2 text-rally-ink">My absence notices</h2>
        {absencesQuery.isError ? (
          <p role="alert" className="rounded-md bg-status-red-50 p-3 text-sm text-status-red-800">
            Could not load absence notices.
          </p>
        ) : absencesQuery.isLoading ? (
          <ListSkeleton />
        ) : notices.length === 0 ? (
          <PanelEmptyState message="No absence notices yet." />
        ) : (
          <ul className="space-y-2">
            {notices.map((n: AbsenceNoticeView) => (
              <li key={n.notice_id}>
                <Card p={12}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-rally-ink">
                        {formatAcademyDateTime(n.submitted_at, academyTimezone)}
                      </p>
                      {n.notice_window_met === false && (
                        <p className="mt-1 text-xs text-status-amber-800">
                          Submitted inside the notice window
                        </p>
                      )}
                    </div>
                    <Chip variant={n.notice_window_met ? "approved" : "pending"} label={n.notice_window_met ? "ON TIME" : "LATE"} />
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

// --- Makeups ---

function MakeupsPanel() {
  const queryClient = useQueryClient();
  const [selectedAbsence, setSelectedAbsence] = useState<AbsenceNoticeView | null>(null);
  const [targetOccurrenceId, setTargetOccurrenceId] = useState<string>("");

  const academyQuery = useQuery({
    queryKey: ["parent", "academy"],
    queryFn: getParentAcademy,
  });
  const absencesQuery = useQuery({
    queryKey: queryKeys.parent.absences(),
    queryFn: listParentAbsences,
  });
  const makeupsQuery = useQuery({
    queryKey: queryKeys.parent.makeups(),
    queryFn: listParentMakeups,
  });
  const targetsQuery = useQuery({
    queryKey: selectedAbsence
      ? queryKeys.parent.makeupTargets(selectedAbsence.student_id, selectedAbsence.occurrence_id)
      : queryKeys.parent.makeupTargets("none", "none"),
    queryFn: () =>
      listEligibleMakeupTargets({
        student_id: selectedAbsence!.student_id,
        missed_occurrence_id: selectedAbsence!.occurrence_id,
      }),
    enabled: Boolean(selectedAbsence),
  });

  const submitMutation = useMutation({
    mutationFn: submitMakeupRequest,
    onSuccess: () => {
      setSelectedAbsence(null);
      setTargetOccurrenceId("");
      void queryClient.invalidateQueries({ queryKey: queryKeys.parent.makeups() });
    },
  });

  const academyTimezone = academyQuery.data?.timezone ?? null;
  const absences = absencesQuery.data?.notices ?? [];
  const makeups = makeupsQuery.data?.makeups ?? [];
  const targets = targetsQuery.data?.targets ?? [];

  // Absences that don't already have a makeup request against them.
  const requestedOccurrenceIds = new Set(makeups.map((m) => m.missed_occurrence_id));
  const eligibleAbsences = absences.filter((a) => !requestedOccurrenceIds.has(a.occurrence_id));

  return (
    <div className="space-y-4">
      <Card p={16}>
        <h2 className="text-sm font-bold mb-3 text-rally-ink">Request a makeup</h2>

        {submitMutation.isError ? (
          <p role="alert" className="mb-3 rounded-md bg-status-red-50 p-3 text-sm text-status-red-800">
            {submitMutation.error instanceof Error
              ? submitMutation.error.message
              : "Could not submit makeup request."}
          </p>
        ) : null}

        {absencesQuery.isLoading ? (
          <ListSkeleton />
        ) : eligibleAbsences.length === 0 ? (
          <PanelEmptyState message="No missed classes available for a makeup request." />
        ) : (
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (!selectedAbsence) return;
              submitMutation.mutate({
                student_id: selectedAbsence.student_id,
                missed_occurrence_id: selectedAbsence.occurrence_id,
                requested_target_occurrence_id: targetOccurrenceId || undefined,
              });
            }}
          >
            <label className="block text-xs font-semibold text-rally-muted">
              Missed class
              <select
                className="mt-1 min-h-touch w-full rounded-lg border border-rally-line px-3 text-sm"
                value={selectedAbsence?.occurrence_id ?? ""}
                onChange={(e) => {
                  const found = eligibleAbsences.find((a) => a.occurrence_id === e.target.value) ?? null;
                  setSelectedAbsence(found);
                  setTargetOccurrenceId("");
                }}
              >
                <option value="">Select a missed class</option>
                {eligibleAbsences.map((a) => (
                  <option key={a.occurrence_id} value={a.occurrence_id}>
                    Reported {formatAcademyDate(a.submitted_at, academyTimezone)} ({a.session_id})
                  </option>
                ))}
              </select>
            </label>

            {selectedAbsence && (
              <label className="block text-xs font-semibold text-rally-muted">
                Preferred makeup class (optional)
                <select
                  className="mt-1 min-h-touch w-full rounded-lg border border-rally-line px-3 text-sm"
                  value={targetOccurrenceId}
                  onChange={(e) => setTargetOccurrenceId(e.target.value)}
                  disabled={targetsQuery.isLoading}
                >
                  <option value="">
                    {targetsQuery.isLoading
                      ? "Loading available classes…"
                      : targets.length === 0
                        ? "No eligible classes found — admin will assign one"
                        : "No preference"}
                  </option>
                  {targets.map((t) => (
                    <option key={t.occurrence_id} value={t.occurrence_id}>
                      {t.title} — {formatAcademyTimeRange(t.start_at, t.end_at, academyTimezone)} ({t.open_slots} open)
                    </option>
                  ))}
                </select>
              </label>
            )}

            <Button type="submit" variant="primary" full disabled={!selectedAbsence || submitMutation.isPending}>
              {submitMutation.isPending ? "Submitting…" : "Request makeup"}
            </Button>
          </form>
        )}
      </Card>

      <div>
        <h2 className="text-sm font-bold mb-2 text-rally-ink">My makeup requests</h2>
        {makeupsQuery.isError ? (
          <p role="alert" className="rounded-md bg-status-red-50 p-3 text-sm text-status-red-800">
            Could not load makeup requests.
          </p>
        ) : makeupsQuery.isLoading ? (
          <ListSkeleton />
        ) : makeups.length === 0 ? (
          <PanelEmptyState message="No makeup requests yet." />
        ) : (
          <ul className="space-y-2">
            {makeups.map((m: MakeupRequestView) => (
              <li key={m.request_id}>
                <Card p={12}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-rally-ink">
                        Requested {formatAcademyDate(m.created_at, academyTimezone)}
                      </p>
                      <p className="mt-1 text-xs text-rally-muted">
                        Expires {formatAcademyDate(m.expires_at, academyTimezone)}
                      </p>
                      {m.status === "denied" && m.denial_reason && (
                        <p className="mt-1 text-xs text-status-red-600">{m.denial_reason}</p>
                      )}
                    </div>
                    <Chip variant={requestStatusChipVariant(m.status)} label={m.status.toUpperCase()} />
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

// --- Trials ---

function TrialsPanel() {
  const queryClient = useQueryClient();
  const [studentRef, setStudentRef] = useState<TrialRequestStudentRef>("existing_student");
  const [studentId, setStudentId] = useState("");
  const [prospectiveName, setProspectiveName] = useState("");
  const [prospectiveDob, setProspectiveDob] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [preferredStart, setPreferredStart] = useState("");
  const [preferredEnd, setPreferredEnd] = useState("");

  const academyQuery = useQuery({
    queryKey: ["parent", "academy"],
    queryFn: getParentAcademy,
  });
  const childrenQuery = useQuery({
    queryKey: ["parent", "children"],
    queryFn: listParentChildren,
  });
  const sessionsQuery = useQuery({
    queryKey: ["parent", "sessions", "available"],
    queryFn: listAvailableParentSessions,
  });
  const trialsQuery = useQuery({
    queryKey: queryKeys.parent.trials(),
    queryFn: listParentTrialRequests,
  });

  const submitMutation = useMutation({
    mutationFn: submitTrialRequest,
    onSuccess: () => {
      setStudentId("");
      setProspectiveName("");
      setProspectiveDob("");
      setSessionId("");
      setPreferredStart("");
      setPreferredEnd("");
      void queryClient.invalidateQueries({ queryKey: queryKeys.parent.trials() });
    },
  });

  const academyTimezone = academyQuery.data?.timezone ?? null;
  const children = childrenQuery.data?.children ?? [];
  const sessions = sessionsQuery.data?.sessions ?? [];
  const trials = trialsQuery.data?.trials ?? [];

  const canSubmit = useMemo(() => {
    if (!sessionId || !preferredStart || !preferredEnd) return false;
    if (studentRef === "existing_student") return Boolean(studentId);
    return Boolean(prospectiveName.trim());
  }, [sessionId, preferredStart, preferredEnd, studentRef, studentId, prospectiveName]);

  return (
    <div className="space-y-4">
      <Card p={16}>
        <h2 className="text-sm font-bold mb-3 text-rally-ink">Request a trial class</h2>

        {submitMutation.isError ? (
          <p role="alert" className="mb-3 rounded-md bg-status-red-50 p-3 text-sm text-status-red-800">
            {submitMutation.error instanceof Error
              ? submitMutation.error.message
              : "Could not submit trial request."}
          </p>
        ) : null}

        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (!canSubmit) return;
            submitMutation.mutate({
              student_ref: studentRef,
              requested_session_id: sessionId,
              preferred_start: preferredStart,
              preferred_end: preferredEnd,
              student_id: studentRef === "existing_student" ? studentId : undefined,
              prospective_child_name: studentRef === "prospective" ? prospectiveName : undefined,
              prospective_child_dob: studentRef === "prospective" ? prospectiveDob || undefined : undefined,
            });
          }}
        >
          <fieldset className="flex gap-4 text-xs font-semibold text-rally-muted">
            <legend className="sr-only">Who is this trial for?</legend>
            <label className="flex items-center gap-1.5">
              <input
                type="radio"
                name="student-ref"
                checked={studentRef === "existing_student"}
                onChange={() => setStudentRef("existing_student")}
              />
              Existing child
            </label>
            <label className="flex items-center gap-1.5">
              <input
                type="radio"
                name="student-ref"
                checked={studentRef === "prospective"}
                onChange={() => setStudentRef("prospective")}
              />
              New child
            </label>
          </fieldset>

          {studentRef === "existing_student" ? (
            <label className="block text-xs font-semibold text-rally-muted">
              Child
              <select
                className="mt-1 min-h-touch w-full rounded-lg border border-rally-line px-3 text-sm"
                value={studentId}
                onChange={(e) => setStudentId(e.target.value)}
              >
                <option value="">Select a child</option>
                {children.map((c: ParentChild) => (
                  <option key={c.student_id} value={c.student_id}>
                    {c.full_name}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <div className="space-y-3">
              <label className="block text-xs font-semibold text-rally-muted">
                Child&apos;s name
                <input
                  type="text"
                  className="mt-1 min-h-touch w-full rounded-lg border border-rally-line px-3 text-sm"
                  value={prospectiveName}
                  onChange={(e) => setProspectiveName(e.target.value)}
                  placeholder="Full name"
                />
              </label>
              <label className="block text-xs font-semibold text-rally-muted">
                Date of birth (optional)
                <input
                  type="date"
                  className="mt-1 min-h-touch w-full rounded-lg border border-rally-line px-3 text-sm"
                  value={prospectiveDob}
                  onChange={(e) => setProspectiveDob(e.target.value)}
                />
              </label>
            </div>
          )}

          <label className="block text-xs font-semibold text-rally-muted">
            Session
            <select
              className="mt-1 min-h-touch w-full rounded-lg border border-rally-line px-3 text-sm"
              value={sessionId}
              onChange={(e) => setSessionId(e.target.value)}
              disabled={sessionsQuery.isLoading}
            >
              <option value="">
                {sessionsQuery.isLoading ? "Loading sessions…" : "Select a session"}
              </option>
              {sessions.map((s) => (
                <option key={s.session_id} value={s.session_id}>
                  {s.title} — {formatAcademyTimeRange(s.start_at, s.end_at, academyTimezone)}
                </option>
              ))}
            </select>
          </label>

          <div className="grid grid-cols-2 gap-3">
            <label className="block text-xs font-semibold text-rally-muted">
              Preferred start
              <input
                type="date"
                className="mt-1 min-h-touch w-full rounded-lg border border-rally-line px-3 text-sm"
                value={preferredStart}
                onChange={(e) => setPreferredStart(e.target.value)}
              />
            </label>
            <label className="block text-xs font-semibold text-rally-muted">
              Preferred end
              <input
                type="date"
                className="mt-1 min-h-touch w-full rounded-lg border border-rally-line px-3 text-sm"
                value={preferredEnd}
                onChange={(e) => setPreferredEnd(e.target.value)}
              />
            </label>
          </div>

          <Button type="submit" variant="primary" full disabled={!canSubmit || submitMutation.isPending}>
            {submitMutation.isPending ? "Submitting…" : "Request trial"}
          </Button>
        </form>
      </Card>

      <div>
        <h2 className="text-sm font-bold mb-2 text-rally-ink">My trial requests</h2>
        {trialsQuery.isError ? (
          <p role="alert" className="rounded-md bg-status-red-50 p-3 text-sm text-status-red-800">
            Could not load trial requests.
          </p>
        ) : trialsQuery.isLoading ? (
          <ListSkeleton />
        ) : trials.length === 0 ? (
          <PanelEmptyState message="No trial requests yet." />
        ) : (
          <ul className="space-y-2">
            {trials.map((t: TrialRequestView) => (
              <li key={t.request_id}>
                <Card p={12}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-rally-ink">
                        {t.prospective_child_name ?? "Existing child"}
                      </p>
                      <p className="mt-1 text-xs text-rally-muted">
                        Requested {formatAcademyDate(t.created_at, academyTimezone)} · {t.preferred_start} – {t.preferred_end}
                      </p>
                      {t.status === "denied" && t.denial_reason && (
                        <p className="mt-1 text-xs text-status-red-600">{t.denial_reason}</p>
                      )}
                    </div>
                    <Chip variant={requestStatusChipVariant(t.status)} label={t.status.toUpperCase()} />
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

// --- Shared list states ---

function ListSkeleton() {
  return (
    <div className="space-y-2">
      {[0, 1].map((i) => (
        <div key={i} className="h-14 rounded-lg shimmer" />
      ))}
    </div>
  );
}

function PanelEmptyState({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-rally-line bg-white p-6">
      <EmptyState title={message} compact />
    </div>
  );
}
