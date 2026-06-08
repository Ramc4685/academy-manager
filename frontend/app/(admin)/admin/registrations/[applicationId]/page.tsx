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

export default function AdminRegistrationDetailPage() {
  const params = useParams<{ applicationId: string }>();
  const applicationId = decodeURIComponent(params.applicationId);
  const router = useRouter();
  const queryClient = useQueryClient();
  const [overrideReason, setOverrideReason] = useState("");
  const [waitlistReason, setWaitlistReason] = useState("");
  const [rejectReason, setRejectReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const query = useQuery({
    queryKey: queryKeys.admin.registrationDetail(applicationId),
    queryFn: () => getAdminRegistration(applicationId),
    retry: false,
  });

  const refresh = (detail?: AdminRegistrationDetail) => {
    if (detail) {
      queryClient.setQueryData(queryKeys.admin.registrationDetail(applicationId), detail);
    }
    void queryClient.invalidateQueries({ queryKey: queryKeys.admin.registrations() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.admin.registrationDetail(applicationId) });
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
    mutationFn: () =>
      rejectAdminRegistration(applicationId, {
        reason: rejectReason.trim() || "Registration rejected by admin",
      }),
    onSuccess: () => {
      refresh();
      router.push("/admin/registrations");
    },
    onError: (err: Error) => setError(err.message),
  });

  return (
    <section data-testid="admin-registration-detail" className="space-y-6">
      <Link href="/admin/registrations" className="text-sm font-semibold text-rally-cobalt hover:underline">
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

          <LaneHeader index="02" title="Decision" />
          <Card p={20}>
            <div className="grid gap-4 lg:grid-cols-3">
              <ActionPanel
                title="Approve"
                copy="Create the student record, reserve the roster seat, and activate enrollment."
                textareaLabel="Waiver override reason"
                textareaValue={overrideReason}
                onTextareaChange={setOverrideReason}
                buttonLabel={approveMutation.isPending ? "Approving..." : "Approve"}
                disabled={approveMutation.isPending || query.data.status !== "PENDING_APPROVAL"}
                onClick={() => {
                  setError(null);
                  approveMutation.mutate();
                }}
              />
              <ActionPanel
                title="Waitlist"
                copy="Create the student record and place the registration into the selected session queue."
                textareaLabel="Waitlist reason"
                textareaValue={waitlistReason}
                onTextareaChange={setWaitlistReason}
                buttonLabel={waitlistMutation.isPending ? "Saving..." : "Waitlist"}
                disabled={waitlistMutation.isPending || query.data.status !== "PENDING_APPROVAL"}
                onClick={() => {
                  setError(null);
                  waitlistMutation.mutate();
                }}
              />
              <ActionPanel
                title="Reject"
                copy="Decline the registration with an internal reason."
                textareaLabel="Reject reason"
                textareaValue={rejectReason}
                onTextareaChange={setRejectReason}
                buttonLabel={rejectMutation.isPending ? "Rejecting..." : "Reject"}
                disabled={rejectMutation.isPending || query.data.status !== "PENDING_APPROVAL"}
                onClick={() => {
                  setError(null);
                  rejectMutation.mutate();
                }}
              />
            </div>
            {error && <p role="alert" className="mt-4 text-sm text-red-700">{error}</p>}
          </Card>
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
  onClick,
}: {
  title: string;
  copy: string;
  textareaLabel: string;
  textareaValue: string;
  onTextareaChange: (value: string) => void;
  buttonLabel: string;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <div className="rounded-md border border-neutral-200 p-4">
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
