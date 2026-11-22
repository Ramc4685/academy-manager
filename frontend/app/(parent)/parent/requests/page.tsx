"use client";

import { Suspense, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import { Button } from "@/components/ds/button";
import { EmptyState } from "@/components/ds/empty-state";
import { WaitlistOffers } from "@/components/parent/waitlist-offers";
import { AssignedClassDetails } from "@/components/parent/one-time-class";
import { queryKeys } from "@/lib/query/keys";
import {
  makeupCandidateKey,
  makeupCandidateLabel,
  makeupEmptyMessage,
  requestStatusChipVariant,
} from "@/lib/parent-requests";
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
  listMakeupCandidates,
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

const ALL_TABS: { id: RequestTab; label: string }[] = [
  { id: "absences", label: "Absences" },
  { id: "makeups", label: "Makeups" },
  { id: "trials", label: "Trials" },
];

export default function ParentRequestsPage() {
  const [tab, setTab] = useState<RequestTab>("absences");
  const academyQuery = useQuery({
    queryKey: queryKeys.parent.academy(),
    queryFn: getParentAcademy,
  });
  // Settings overhaul Phase 1 Lane C: hide (not just disable) an action the
  // academy has switched off. Undefined switches (query still loading)
  // default true, matching the server's own default.
  const selfService = academyQuery.data?.self_service;
  const TABS = ALL_TABS.filter((t) => {
    if (t.id === "absences") return selfService?.can_report_absence ?? true;
    if (t.id === "makeups") return selfService?.can_request_makeup ?? true;
    if (t.id === "trials") return selfService?.can_request_trial ?? true;
    return true;
  });
  const activeTab = TABS.some((t) => t.id === tab) ? tab : (TABS[0]?.id ?? "absences");

  return (
    <section data-testid="parent-requests" className="space-y-4">
      <div className="animate-fade-in-up">
        <h1 className="font-display text-2xl font-bold tracking-tight text-rally-ink">Requests</h1>
        <p className="text-sm mt-0.5 text-rally-muted">Absences, makeups &amp; trial classes</p>
      </div>

      {/* X2: the "a seat opened" email lands here (?offer=<waitlist_id>). */}
      <Suspense fallback={null}>
        <WaitlistOffersFromLink />
      </Suspense>

      {/* #843: the inactive tab label was rally-muted (#64748b) on the
          rally-line track (#e2e8f0) — 3.86:1, under AA. slate-600 clears it. */}
      {TABS.length > 1 && (
        <div role="tablist" aria-label="Request type" className="flex gap-1 rounded-xl bg-rally-line p-1">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={activeTab === t.id}
              onClick={() => setTab(t.id)}
              className={`min-h-touch flex-1 rounded-lg text-sm font-semibold transition-all duration-150 ${
                activeTab === t.id
                  ? "bg-white text-rally-ink shadow-[0_1px_2px_rgba(0,0,0,0.06)]"
                  : "bg-transparent text-status-slate-600"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      )}

      {TABS.length === 0 ? (
        <EmptyState
          title="No requests available"
          description="Your academy has turned off self-service requests. Contact them directly for absences, makeups or trials."
        />
      ) : (
        <>
          {activeTab === "absences" && <AbsencesPanel />}
          {activeTab === "makeups" && <MakeupsPanel />}
          {activeTab === "trials" && <TrialsPanel />}
        </>
      )}
    </section>
  );
}

function WaitlistOffersFromLink() {
  const offerId = useSearchParams().get("offer");
  return <WaitlistOffers highlightId={offerId} />;
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
  const nameById = new Map(children.map((c: ParentChild) => [c.student_id, c.full_name]));
  const academyTimezone = academyQuery.data?.timezone ?? null;
  // A cancelled class cannot be missed, so it must not be offered as the
  // subject of an absence notice (#671).
  const occurrences = (scheduleQuery.data?.entries ?? []).filter(
    (entry: ParentScheduleEntry) => entry.status !== "cancelled",
  );
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
                      <p className="text-xs font-semibold text-rally-subtle">
                        {nameById.get(n.student_id) ?? "Your child"}
                      </p>
                      <p data-testid={`absence-class-${n.notice_id}`} className="text-sm font-semibold text-rally-ink">
                        {n.missed_class
                          ? `${n.missed_class.session_title} — ${formatAcademyTimeRange(
                              n.missed_class.start_at,
                              n.missed_class.end_at,
                              n.missed_class.timezone ?? academyTimezone,
                            )}`
                          : "Class details unavailable"}
                      </p>
                      <p className="mt-0.5 text-xs text-rally-subtle">
                        Submitted {formatAcademyDateTime(n.submitted_at, academyTimezone)}
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
  const [selectedKey, setSelectedKey] = useState<string>("");
  const [targetOccurrenceId, setTargetOccurrenceId] = useState<string>("");

  const academyQuery = useQuery({
    queryKey: ["parent", "academy"],
    queryFn: getParentAcademy,
  });
  const childrenQuery = useQuery({
    queryKey: ["parent", "children"],
    queryFn: listParentChildren,
  });
  // #1041: the server's own eligibility (notice rule, expiry window, an
  // active request already open), so a class needs no notice when the
  // academy doesn't require one, and a denied request can be asked again.
  const candidatesQuery = useQuery({
    queryKey: queryKeys.parent.makeupCandidates(),
    queryFn: listMakeupCandidates,
  });
  const makeupsQuery = useQuery({
    queryKey: queryKeys.parent.makeups(),
    queryFn: listParentMakeups,
  });

  const candidates = candidatesQuery.data?.candidates ?? [];
  const ineligible = candidatesQuery.data?.ineligible ?? [];
  const selected = candidates.find((c) => makeupCandidateKey(c) === selectedKey) ?? null;

  const targetsQuery = useQuery({
    queryKey: selected
      ? queryKeys.parent.makeupTargets(selected.student_id, selected.occurrence_id)
      : queryKeys.parent.makeupTargets("none", "none"),
    queryFn: () =>
      listEligibleMakeupTargets({
        student_id: selected!.student_id,
        missed_occurrence_id: selected!.occurrence_id,
      }),
    enabled: Boolean(selected),
  });

  const submitMutation = useMutation({
    mutationFn: submitMakeupRequest,
    onSuccess: () => {
      setSelectedKey("");
      setTargetOccurrenceId("");
      // Prefix match also refreshes the candidate list under ["parent","makeups"].
      void queryClient.invalidateQueries({ queryKey: queryKeys.parent.makeups() });
    },
  });

  const academyTimezone = academyQuery.data?.timezone ?? null;
  const children = childrenQuery.data?.children ?? [];
  const nameById = new Map(children.map((c: ParentChild) => [c.student_id, c.full_name]));
  const makeups = makeupsQuery.data?.makeups ?? [];
  const targets = targetsQuery.data?.targets ?? [];

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

        {candidatesQuery.isError ? (
          <div role="alert" className="rounded-md bg-status-red-50 p-3 text-sm text-status-red-800">
            <p>Could not load your missed classes.</p>
            <Button variant="secondary" onClick={() => void candidatesQuery.refetch()}>
              Try again
            </Button>
          </div>
        ) : candidatesQuery.isLoading ? (
          <ListSkeleton />
        ) : candidates.length === 0 ? (
          <PanelEmptyState
            message={makeupEmptyMessage(
              candidatesQuery.data ?? { makeups_enabled: true, requires_notice: false },
            )}
          />
        ) : (
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (!selected) return;
              submitMutation.mutate({
                student_id: selected.student_id,
                missed_occurrence_id: selected.occurrence_id,
                requested_target_occurrence_id: targetOccurrenceId || undefined,
              });
            }}
          >
            <label className="block text-xs font-semibold text-rally-muted">
              Missed class
              <select
                className="mt-1 min-h-touch w-full rounded-lg border border-rally-line px-3 text-sm"
                value={selectedKey}
                onChange={(e) => {
                  setSelectedKey(e.target.value);
                  setTargetOccurrenceId("");
                }}
              >
                <option value="">Select a missed class</option>
                {candidates.map((c) => (
                  <option key={makeupCandidateKey(c)} value={makeupCandidateKey(c)}>
                    {makeupCandidateLabel(c, academyTimezone)}
                  </option>
                ))}
              </select>
            </label>

            {selected && (
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

            <Button type="submit" variant="primary" full disabled={!selected || submitMutation.isPending}>
              {submitMutation.isPending ? "Submitting…" : "Request makeup"}
            </Button>
          </form>
        )}
        {ineligible.length > 0 && (
          <div className="mt-4" data-testid="makeup-ineligible">
            <h3 className="text-xs font-semibold text-rally-muted">Can&apos;t be made up</h3>
            <ul className="mt-2 space-y-2">
              {ineligible.map((row) => (
                <li
                  key={makeupCandidateKey(row)}
                  className="rounded-lg border border-rally-line p-3 text-sm"
                >
                  <p className="font-semibold text-rally-ink">
                    {row.student_name} — {row.class_title} —{" "}
                    {formatAcademyDateTime(row.start_at, academyTimezone)}
                  </p>
                  <p className="mt-1 text-xs text-rally-muted">{row.reason}</p>
                </li>
              ))}
            </ul>
          </div>
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
                      <p className="text-xs font-semibold text-rally-subtle">
                        {nameById.get(m.student_id) ?? "Your child"}
                      </p>
                      <p className="text-sm font-semibold text-rally-ink">
                        Requested {formatAcademyDate(m.created_at, academyTimezone)}
                      </p>
                      <p className="mt-1 text-xs text-rally-muted">
                        Expires {formatAcademyDate(m.expires_at, academyTimezone)}
                      </p>
                      {m.status === "denied" && m.denial_reason && (
                        <p className="mt-1 text-xs text-status-red-600">{m.denial_reason}</p>
                      )}
                      <AssignedClassDetails
                        kind="makeup"
                        assigned={m.assigned_class}
                        academyTimezone={academyTimezone}
                      />
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
  const trialNameById = new Map(children.map((c: ParentChild) => [c.student_id, c.full_name]));

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
                        {t.prospective_child_name ??
                          (t.student_id ? trialNameById.get(t.student_id) : undefined) ??
                          "Existing child"}
                      </p>
                      <p className="mt-1 text-xs text-rally-muted">
                        Requested {formatAcademyDate(t.created_at, academyTimezone)} · {t.preferred_start} – {t.preferred_end}
                      </p>
                      {t.status === "denied" && t.denial_reason && (
                        <p className="mt-1 text-xs text-status-red-600">{t.denial_reason}</p>
                      )}
                      <AssignedClassDetails
                        kind="trial"
                        assigned={t.assigned_class}
                        academyTimezone={academyTimezone}
                      />
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
