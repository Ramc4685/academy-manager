"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  acceptParentWaiver,
  getParentCurrentWaiver,
  type ParentWaiverItemView,
  type ParentWaiverStatus,
  type ParentWaiverStudentView,
} from "@/lib/api/parent";
import { Skeleton } from "@/components/ds/skeleton";
import { EmptyState } from "@/components/ds/empty-state";
import { Card } from "@/components/ds/card";
import { Chip, type ChipVariant } from "@/components/ds/chip";
import { useToast } from "@/components/ds/toast";
import { AiVideoConsentCard } from "@/components/parent/ai-video-consent";
import { WaiverSignBlock, type WaiverSignChild } from "@/components/parent/waiver-sign-block";
import type { ApiError } from "@/lib/api/client";
import { waiverSignLabel } from "@/lib/parent/waiver-label";
import { WaiverText } from "@/components/waivers/waiver-text";
import { initialsComplete, initialsNeeded, parseWaiverSections } from "@/lib/waivers/sections";

export default function ParentWaiversPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [accepted, setAccepted] = useState(false);
  // waiver_template_id -> {section key: initials}
  const [initials, setInitials] = useState<Record<string, Record<string, string>>>({});
  const waiverQuery = useQuery({
    queryKey: ["parent", "waivers", "current"],
    queryFn: getParentCurrentWaiver,
    retry: false,
  });
  const acceptMutation = useMutation({
    mutationFn: (input: { signerName: string; studentIds: string[] }) =>
      acceptParentWaiver({
        signer_name: input.signerName,
        consent: true,
        student_ids: input.studentIds,
        initials,
      }),
    onSuccess: () => {
      setAccepted(true);
      toast({ kind: "success", title: "Signed. A copy is on its way to your email." });
      void queryClient.invalidateQueries({ queryKey: ["parent", "waivers", "current"] });
      void waiverQuery.refetch();
    },
  });

  const waiver = waiverQuery.data;
  // Every waiver this parent's children must sign. An older API reply has only
  // the flat first waiver, which is the same single item.
  const items = useMemo<ParentWaiverItemView[]>(() => {
    if (!waiver) return [];
    if (waiver.waivers && waiver.waivers.length > 0) return waiver.waivers;
    return [
      {
        waiver_template_id: waiver.waiver_template_id ?? "current",
        title: waiver.title,
        version: waiver.version,
        body: waiver.body,
        students: waiver.students,
      },
    ];
  }, [waiver]);
  const allStudents = useMemo(() => items.flatMap((item) => item.students), [items]);
  const needsSignature = allStudents.some((student) => student.status !== "signed");
  // Each child who still owes a signature on any waiver, once.
  // A child without a date of birth cannot sign an age-split waiver yet.
  const childrenToSign = useMemo<WaiverSignChild[]>(() => {
    const seen = new Map<string, WaiverSignChild>();
    for (const student of allStudents) {
      if (owes(student) && !student.date_of_birth_missing) seen.set(student.student_id, student);
    }
    return Array.from(seen.values());
  }, [allStudents]);
  const missingBirthDate = useMemo(
    () =>
      Array.from(
        new Set(
          allStudents
            .filter((student) => owes(student) && student.date_of_birth_missing)
            .map((student) => student.student_name),
        ),
      ),
    [allStudents],
  );
  // Initialled sections on the paths of the children still to sign, per waiver.
  const needed = useMemo(
    () =>
      Object.fromEntries(
        items.map((item) => [
          item.waiver_template_id,
          initialsNeeded(
            parseWaiverSections(item.body),
            item.students
              .filter((student) => owes(student) && !student.date_of_birth_missing)
              .map((student) => student.signing_path ?? null),
          ),
        ]),
      ),
    [items],
  );
  const initialsDone = items.every((item) =>
    initialsComplete(needed[item.waiver_template_id] ?? [], initials[item.waiver_template_id]),
  );
  const several = items.length > 1;

  if (waiverQuery.isPending) {
    return (
      <section className="space-y-4 animate-fade-in-up">
        <div className="mb-4 space-y-2">
          <Skeleton variant="line" width="10rem" height="1.75rem" />
          <Skeleton variant="line" width="6rem" />
        </div>
        <Card className="overflow-hidden" p={0}>
          <div className="p-4 space-y-3">
            {[1, 2].map((i) => (
              <div key={i} className="flex items-center justify-between gap-3 rounded-xl p-3 bg-rally-cobalt-50">
                <div className="h-3 w-32 rounded shimmer" />
                <div className="h-5 w-16 rounded-full shimmer" />
              </div>
            ))}
          </div>
        </Card>
        <Skeleton variant="block" height="10rem" className="rounded-2xl border border-rally-line" />
        <Card className="overflow-hidden" p={0}>
          <div className="p-4 space-y-3">
            <div className="h-3 w-20 rounded shimmer" />
            <div className="h-11 w-full rounded-xl shimmer" />
            <div className="h-12 w-full rounded-xl shimmer" />
          </div>
        </Card>
      </section>
    );
  }

  if (waiverQuery.isError || !waiver) {
    return (
      <section className="animate-fade-in-up">
        <div className="mb-4">
          <h1 className="font-display text-2xl font-bold tracking-tight text-rally-ink">Waivers</h1>
        </div>
        <div
          className="rounded-2xl p-4 text-sm bg-status-red-50 border border-status-red-200 text-status-red-800"
          role="alert"
        >
          Could not load waiver. Please try refreshing the page.
        </div>
      </section>
    );
  }

  if (!waiver.required) {
    return (
      <section data-testid="parent-waivers" className="space-y-4 animate-fade-in-up">
        <div className="mb-4">
          <h1 className="font-display text-2xl font-bold tracking-tight text-rally-ink">Waivers</h1>
          <p className="text-sm mt-0.5 text-rally-muted">Liability &amp; consent forms</p>
        </div>
        <EmptyState
          title="No waiver required"
          description="You're all set — there are no forms to sign right now."
        />
        <AiVideoConsentCard />
      </section>
    );
  }

  return (
    <section data-testid="parent-waivers" className="space-y-4 animate-fade-in-up">
      {/* Header */}
      <div className="mb-4">
        <h1 className="font-display text-2xl font-bold tracking-tight text-rally-ink">
          {several ? "Required waivers" : (waiver.title ?? "Required waiver")}
        </h1>
        <p className="text-sm mt-0.5 text-rally-muted">
          {several
            ? `${items.length} waivers to sign`
            : `Version ${waiver.version ?? "current"}`}
        </p>
      </div>

      {items.map((item) => (
        <div
          key={item.waiver_template_id}
          data-testid={`parent-waiver-${item.waiver_template_id}`}
          className="space-y-4"
        >
          {several && (
            <h2 className="font-display text-lg font-semibold tracking-tight text-rally-ink">
              {item.title ?? "Waiver"}
              <span className="ml-2 text-sm font-normal text-rally-muted">
                Version {item.version ?? "current"}
              </span>
            </h2>
          )}

          {/* Children status card */}
          <Card className="overflow-hidden" p={0}>
            <div className="px-4 pt-4 pb-1">
              <p className="text-[10px] font-bold uppercase tracking-widest mb-2.5 text-rally-cobalt-600">
                Children
              </p>
            </div>
            <div className="px-4 pb-4 space-y-2">
              {item.students.map((student) => (
                <div
                  key={student.student_id}
                  className="flex items-center justify-between gap-3 rounded-xl px-3 py-2.5 text-sm bg-rally-cobalt-50"
                >
                  <span className="font-medium truncate text-rally-ink">{student.student_name}</span>
                  <span className="flex shrink-0 items-center gap-2">
                    {student.status === "signed" && student.waiver_signature_id && (
                      <Link
                        href={`/parent/waivers/signatures/${encodeURIComponent(student.waiver_signature_id)}`}
                        className="text-xs font-semibold text-rally-cobalt-600 underline-offset-2 hover:underline"
                      >
                        Signed copy
                      </Link>
                    )}
                    <WaiverStatusPill status={student.status} />
                  </span>
                </div>
              ))}
            </div>
          </Card>

          {/* Waiver body */}
          <article className="max-h-[480px] overflow-y-auto rounded-2xl border border-rally-line bg-white p-4">
            <WaiverText
              body={item.body}
              needInitials={needed[item.waiver_template_id]}
              initials={initials[item.waiver_template_id]}
              onInitials={(key, value) =>
                setInitials((current) => ({
                  ...current,
                  [item.waiver_template_id]: { ...current[item.waiver_template_id], [key]: value },
                }))
              }
            />
          </article>
        </div>
      ))}

      {/* Signature / status card */}
      {needsSignature ? (
        <Card>
          {accepted && (
            <p className="mb-3 rounded-xl px-3 py-2 text-sm bg-status-green-50 text-status-green-800" role="status">
              Signed. A copy is on its way to your email.
            </p>
          )}
          {missingBirthDate.length > 0 && (
            <p className="mb-3 rounded-xl px-3 py-2 text-sm bg-status-amber-50 text-status-amber-800" role="status">
              Add a date of birth for {missingBirthDate.join(", ")} in{" "}
              <Link href="/parent/profile" className="font-semibold underline">
                your profile
              </Link>{" "}
              to sign for them. This waiver differs for participants under and over 18.
            </p>
          )}
          <WaiverSignBlock
            childrenToSign={childrenToSign}
            consentText={waiver.consent_text}
            busy={acceptMutation.isPending}
            error={acceptMutation.isError ? signErrorMessage(acceptMutation.error) : null}
            label={(chosen) =>
              waiverSignLabel(
                chosen.map((child) => ({ ...child, status: "pending" as const })),
                items.length,
              )
            }
            blocked={initialsDone ? null : "Initial each marked section above to sign."}
            onSign={(input) => acceptMutation.mutate(input)}
          />
        </Card>
      ) : (
        <div className="rounded-2xl p-4 text-sm bg-status-green-50 border border-status-green-500/30 text-status-green-800">
          {several
            ? "Current waivers are signed for all active children."
            : "Current waiver is signed for all active children."}
        </div>
      )}

      <AiVideoConsentCard />
    </section>
  );
}

function owes(student: ParentWaiverStudentView): boolean {
  return student.status === "pending" || student.status === "outdated";
}

const WAIVER_STATUS_CHIP: Record<ParentWaiverStatus, { variant: ChipVariant; label: string }> = {
  signed: { variant: "approved", label: "Signed" },
  pending: { variant: "pending", label: "Needed" },
  outdated: { variant: "denied", label: "Outdated" },
  not_required: { variant: "expired", label: "Not required" },
};

function WaiverStatusPill({ status }: { status: ParentWaiverStatus }) {
  const spec = WAIVER_STATUS_CHIP[status] ?? WAIVER_STATUS_CHIP.not_required;
  return <Chip variant={spec.variant} label={spec.label} />;
}

function signErrorMessage(error: unknown): string {
  const apiError = error as ApiError | null;
  if (apiError?.code === "Onboarding.WaiverDateOfBirthMissing") {
    return "Add your child's date of birth in your profile, then sign.";
  }
  if (apiError?.code === "Onboarding.WaiverSignatureIncomplete") {
    return "Initial each marked section to sign.";
  }
  if (apiError?.status === 422) {
    return "Type your full name and tick the consent box to sign.";
  }
  return "Could not sign the waiver. Please try again.";
}
