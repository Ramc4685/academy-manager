"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  acceptParentWaiver,
  getParentCurrentWaiver,
  type ParentWaiverStatus,
} from "@/lib/api/parent";
import { Skeleton } from "@/components/ds/skeleton";
import { EmptyState } from "@/components/ds/empty-state";
import { Card } from "@/components/ds/card";
import { Button } from "@/components/ds/button";
import { Chip, type ChipVariant } from "@/components/ds/chip";
import { useToast } from "@/components/ds/toast";

export default function ParentWaiversPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [signerName, setSignerName] = useState("");
  const [accepted, setAccepted] = useState(false);
  const waiverQuery = useQuery({
    queryKey: ["parent", "waivers", "current"],
    queryFn: getParentCurrentWaiver,
    retry: false,
  });
  const acceptMutation = useMutation({
    mutationFn: () => acceptParentWaiver({ signer_name: signerName.trim() || null }),
    onSuccess: () => {
      setAccepted(true);
      toast({ kind: "success", title: "Waiver accepted for your active child(ren)." });
      void queryClient.invalidateQueries({ queryKey: ["parent", "waivers", "current"] });
      void waiverQuery.refetch();
    },
  });

  const waiver = waiverQuery.data;
  const needsSignature = useMemo(
    () => (waiver?.students ?? []).some((student) => student.status !== "signed"),
    [waiver?.students],
  );

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
      </section>
    );
  }

  return (
    <section data-testid="parent-waivers" className="space-y-4 animate-fade-in-up">
      {/* Header */}
      <div className="mb-4">
        <h1 className="font-display text-2xl font-bold tracking-tight text-rally-ink">
          {waiver.title ?? "Required waiver"}
        </h1>
        <p className="text-sm mt-0.5 text-rally-muted">Version {waiver.version ?? "current"}</p>
      </div>

      {/* Children status card */}
      <Card className="overflow-hidden" p={0}>
        <div className="px-4 pt-4 pb-1">
          <p className="text-[10px] font-bold uppercase tracking-widest mb-2.5 text-rally-cobalt-600">
            Children
          </p>
        </div>
        <div className="px-4 pb-4 space-y-2">
          {waiver.students.map((student) => (
            <div
              key={student.student_id}
              className="flex items-center justify-between gap-3 rounded-xl px-3 py-2.5 text-sm bg-rally-cobalt-50"
            >
              <span className="font-medium truncate text-rally-ink">{student.student_name}</span>
              <WaiverStatusPill status={student.status} />
            </div>
          ))}
        </div>
      </Card>

      {/* Waiver body */}
      <article className="max-h-[360px] overflow-y-auto rounded-2xl border border-rally-line bg-white p-4 text-sm leading-6 text-rally-ink">
        {waiver.body || "Waiver text is not available."}
      </article>

      {/* Signature / status card */}
      {needsSignature ? (
        <Card>
          <label className="block text-sm font-medium text-rally-ink">
            Signer name
            <input
              value={signerName}
              onChange={(event) => setSignerName(event.target.value)}
              className="mt-2 h-11 w-full rounded-xl px-3 text-sm outline-none transition-colors border border-rally-line text-rally-ink"
              placeholder="Parent or guardian name"
            />
          </label>
          {acceptMutation.isError && (
            <p
              className="mt-3 rounded-xl px-3 py-2 text-sm bg-status-red-50 text-status-red-800"
              role="alert"
            >
              Could not accept waiver. Please try again.
            </p>
          )}
          {accepted && (
            <p className="mt-3 rounded-xl px-3 py-2 text-sm bg-status-green-50 text-status-green-800" role="status">
              Waiver accepted for your active child(ren).
            </p>
          )}
          <Button
            type="button"
            onClick={() => acceptMutation.mutate()}
            disabled={acceptMutation.isPending}
            full
            variant="volt"
            className="mt-4 disabled:opacity-60"
          >
            {acceptMutation.isPending ? "Accepting..." : "Accept waiver"}
          </Button>
        </Card>
      ) : (
        <div className="rounded-2xl p-4 text-sm bg-status-green-50 border border-status-green-500/30 text-status-green-800">
          Current waiver is signed for all active children.
        </div>
      )}
    </section>
  );
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
