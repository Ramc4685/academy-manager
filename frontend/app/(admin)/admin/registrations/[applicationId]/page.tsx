"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  approveAdminRegistration,
  getAdminRegistration,
  rejectAdminRegistration,
  waitlistAdminRegistration,
  type AdminRegistrationDetail,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Card, Chip, LaneHeader, Overline } from "@/components/ds";
import { ConfirmActionDialog } from "@/components/admin/confirm-action-dialog";

/** The three decisions, and the second look each one now needs (#838). */
type Decision = "approve" | "waitlist" | "reject";

export default function AdminRegistrationDetailPage() {
  const params = useParams<{ applicationId: string }>();
  const applicationId = decodeURIComponent(params.applicationId);
  const router = useRouter();
  const queryClient = useQueryClient();
  const [overrideReason, setOverrideReason] = useState("");
  const [waitlistReason, setWaitlistReason] = useState("");
  const [rejectReason, setRejectReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<Decision | null>(null);

  const query = useQuery({
    queryKey: queryKeys.admin.registrationDetail(applicationId),
    queryFn: () => getAdminRegistration(applicationId),
    retry: false,
  });

  const refresh = (detail?: AdminRegistrationDetail) => {
    if (detail) {
      queryClient.setQueryData(queryKeys.admin.registrationDetail(applicationId), detail);
    }
    void queryClient.invalidateQueries({
      queryKey: queryKeys.admin.registrations(),
      exact: true,
    });
  };

  const approveMutation = useMutation({
    mutationFn: () =>
      approveAdminRegistration(applicationId, {
        waiver_override_reason: overrideReason.trim() || null,
      }),
    onSuccess: refresh,
    onError: (err: Error) => setError(err.message),
  });
  const waitlistMutation = useMutation({
    mutationFn: () =>
      waitlistAdminRegistration(applicationId, {
        reason: waitlistReason.trim() || "Registration waitlisted by admin",
      }),
    onSuccess: refresh,
    onError: (err: Error) => setError(err.message),
  });
  const rejectMutation = useMutation({
    // #838: a blank reason used to be swapped for a canned one, so the family
    // was declined with a sentence nobody wrote. The dialog now refuses to
    // submit without one.
    mutationFn: () => rejectAdminRegistration(applicationId, { reason: rejectReason.trim() }),
    onSuccess: () => {
      refresh();
      router.push("/admin/inbox?tab=registrations");
    },
    onError: (err: Error) => setError(err.message),
  });

  const studentName = query.data?.student_name || "this student";
  const familyLabel = query.data?.parent_name || query.data?.parent_email || "the family";
  const sessionLabel =
    query.data?.session_title || query.data?.selected_session_id || "the requested session";

  const runDecision = (decision: Decision) => {
    setError(null);
    setConfirming(null);
    if (decision === "approve") approveMutation.mutate();
    if (decision === "waitlist") waitlistMutation.mutate();
    if (decision === "reject") rejectMutation.mutate();
  };

  return (
    <section data-testid="admin-registration-detail" className="space-y-6">
      <Link href="/admin/inbox?tab=registrations" className="text-sm font-semibold text-rally-cobalt hover:underline">
        Back to registrations
      </Link>

      {query.isPending && <Card p={20}>Loading registration...</Card>}
      {query.isError && (
        <Card p={20} style={{ borderColor: "#fecaca", background: "#fef2f2" }}>
          <p role="alert" className="text-sm text-red-800">Could not load registration.</p>
        </Card>
      )}
      {query.data && (
        <>
          <LaneHeader index="01" title="Application review" />
          <RegistrationSummary registration={query.data} />

          {query.data.status === "MANUAL_REVIEW" && (
            <Card p={20} style={{ borderColor: "#facc15", background: "#fefce8" }}>
              <p role="alert" className="text-sm font-semibold text-amber-900">
                This child matches more than one legacy record. Resolve the child record with the
                parent before approving, waitlisting, or rejecting this application.
              </p>
            </Card>
          )}

          {query.data.zero_quote_period && !query.data.payment_id && (
            <Card
              data-testid="admin-registration-zero-quote-warning"
              p={20}
              style={{ borderColor: "#facc15", background: "#fefce8" }}
            >
              <p role="alert" className="text-sm font-semibold text-amber-900">
                No payment was collected. This registration was auto-priced at $0 for{" "}
                {query.data.zero_quote_period}. Confirm the quote is correct before approving.
              </p>
            </Card>
          )}

          <LaneHeader index="02" title="Decision" />
          <Card p={20}>
            {/* Issue #747: `grid-cols-1` and `min-w-0` (below) are load-bearing.
                Without an explicit base track the implicit column is sized by the
                panels' intrinsic content, and a grid item defaults to
                `min-width:auto` — so at 390px the Approve/Waitlist/Reject buttons
                were pushed off the right edge with no way to reach them. */}
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
              <ActionPanel
                title="Approve"
                copy="Create the student record, reserve the roster seat, and activate enrollment."
                textareaLabel="Waiver override reason"
                textareaValue={overrideReason}
                onTextareaChange={setOverrideReason}
                buttonLabel={approveMutation.isPending ? "Approving..." : "Approve"}
                disabled={
                  approveMutation.isPending ||
                  !["PENDING_APPROVAL", "APPROVING"].includes(query.data.status)
                }
                onClick={() => {
                  setError(null);
                  setConfirming("approve");
                }}
              />
              <ActionPanel
                title="Waitlist"
                copy="Create the student record and place the registration into the selected session queue."
                textareaLabel="Waitlist reason"
                textareaValue={waitlistReason}
                onTextareaChange={setWaitlistReason}
                buttonLabel={waitlistMutation.isPending ? "Saving..." : "Waitlist"}
                disabled={
                  waitlistMutation.isPending ||
                  !["PENDING_APPROVAL", "WAITLISTING"].includes(query.data.status)
                }
                onClick={() => {
                  setError(null);
                  setConfirming("waitlist");
                }}
              />
              <ActionPanel
                title="Reject"
                copy="Decline the registration with an internal reason."
                textareaLabel="Reject reason"
                textareaValue={rejectReason}
                onTextareaChange={setRejectReason}
                buttonLabel={rejectMutation.isPending ? "Rejecting..." : "Reject"}
                disabled={
                  rejectMutation.isPending ||
                  !rejectReason.trim() ||
                  !["PENDING_APPROVAL", "DECLINING"].includes(query.data.status)
                }
                hint={
                  rejectReason.trim()
                    ? undefined
                    : "Type a reason above — a rejection is never sent without one."
                }
                onClick={() => {
                  setError(null);
                  setConfirming("reject");
                }}
              />
            </div>
            {error && <p role="alert" className="mt-4 text-sm text-red-700">{error}</p>}
          </Card>

          <ConfirmActionDialog
            open={confirming === "approve"}
            onOpenChange={(open) => !open && setConfirming(null)}
            overline="Confirm approval"
            title="Approve this registration?"
            subject={`${studentName} — ${familyLabel}`}
            consequence={
              <>
                <p>
                  Creates the student record and takes a seat in {sessionLabel}. Enrollment goes
                  active, so the family starts being invoiced for it.
                </p>
                <p>{familyLabel} is emailed a confirmation with the session details.</p>
              </>
            }
            confirmLabel="Approve registration"
            confirmVariant="primary"
            pending={approveMutation.isPending}
            onConfirm={() => runDecision("approve")}
          />

          <ConfirmActionDialog
            open={confirming === "waitlist"}
            onOpenChange={(open) => !open && setConfirming(null)}
            overline="Confirm waitlist"
            title="Move this registration to the waitlist?"
            subject={`${studentName} — ${familyLabel}`}
            consequence={
              <>
                <p>
                  Creates the student record but takes no seat in {sessionLabel}. Nothing is
                  invoiced while the registration waits.
                </p>
                <p>{familyLabel} is emailed that they are on the waitlist.</p>
              </>
            }
            confirmLabel="Move to waitlist"
            confirmVariant="primary"
            pending={waitlistMutation.isPending}
            onConfirm={() => runDecision("waitlist")}
          />

          <ConfirmActionDialog
            open={confirming === "reject"}
            onOpenChange={(open) => !open && setConfirming(null)}
            overline="Confirm rejection"
            title="Reject this registration?"
            subject={`${studentName} — ${familyLabel}`}
            consequence={
              <>
                <p>
                  No student record, no seat in {sessionLabel} and no invoice. The application
                  closes and cannot be approved afterwards — the family would have to re-apply.
                </p>
                <p>{familyLabel} is emailed that the registration was declined.</p>
              </>
            }
            reason={{
              label: "Reason for rejecting",
              value: rejectReason,
              onChange: setRejectReason,
              required: true,
              placeholder: "Recorded on the application.",
            }}
            confirmLabel="Reject registration"
            pending={rejectMutation.isPending}
            onConfirm={() => runDecision("reject")}
          />
        </>
      )}
    </section>
  );
}

function RegistrationSummary({ registration }: { registration: AdminRegistrationDetail }) {
  return (
    <div className="grid gap-4 lg:grid-cols-[1.15fr_0.85fr]">
      <Card p={24}>
        <Overline>{registration.status.replaceAll("_", " ")}</Overline>
        <h2 className="mt-1 font-display text-[26px] font-semibold text-rally-ink">
          {registration.student_name || "Unnamed student"}
        </h2>
        <dl className="mt-5 grid gap-4 sm:grid-cols-2">
          <Meta label="Parent" value={registration.parent_name || registration.parent_email} />
          <Meta label="Parent email" value={registration.parent_email} />
          <Meta label="Skill level" value={registration.child_skill_level || "Not provided"} />
          <Meta label="Payment" value={registration.payment_id || "Not linked"} />
        </dl>
      </Card>
      <Card p={20}>
        <Overline>Session and waiver</Overline>
        <div className="mt-4 space-y-4">
          <Meta label="Requested session" value={registration.session_title || registration.selected_session_id || "Not selected"} />
          <Meta label="Capacity" value={registration.session_capacity == null ? "Not reported" : String(registration.session_capacity)} />
          <div>
            <Overline>Waiver</Overline>
            <div className="mt-2">
              <Chip
                variant={registration.waiver_satisfied ? "approved" : "pending"}
                label={registration.waiver_required ? (registration.waiver_satisfied ? "SIGNED" : "NEEDED") : "NOT REQUIRED"}
              />
            </div>
            {registration.waiver_title && (
              <p className="mt-2 text-[12px] text-rally-subtle">
                {registration.waiver_title} {registration.waiver_version ? `v${registration.waiver_version}` : ""}
              </p>
            )}
          </div>
        </div>
      </Card>
    </div>
  );
}

function ActionPanel({
  title,
  copy,
  textareaLabel,
  textareaValue,
  onTextareaChange,
  buttonLabel,
  disabled,
  hint,
  onClick,
}: {
  title: string;
  copy: string;
  textareaLabel: string;
  textareaValue: string;
  onTextareaChange: (value: string) => void;
  buttonLabel: string;
  disabled: boolean;
  hint?: string;
  onClick: () => void;
}) {
  return (
    <div className="min-w-0 rounded-md border border-neutral-200 p-4">
      <h3 className="font-semibold text-rally-base">{title}</h3>
      <p className="mt-2 min-h-[42px] text-[12px] leading-5 text-rally-muted">{copy}</p>
      <label className="mt-4 block text-[12px] font-semibold text-rally-ink">
        {textareaLabel}
        <textarea
          value={textareaValue}
          onChange={(event) => onTextareaChange(event.target.value)}
          className="mt-2 min-h-[82px] w-full rounded-md border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-rally-cobalt"
        />
      </label>
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        className="mt-3 inline-flex min-h-touch items-center rounded-md bg-rally-ink px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
      >
        {buttonLabel}
      </button>
      {hint && <p className="mt-2 text-[12px] leading-5 text-rally-muted">{hint}</p>}
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <Overline>{label}</Overline>
      <dd className="mt-1 text-sm font-semibold text-rally-base">{value}</dd>
    </div>
  );
}
