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

export default function ParentWaiversPage() {
  const queryClient = useQueryClient();
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
        <div className="rounded-2xl overflow-hidden" style={{ background: "white", border: "1px solid var(--rally-line)" }}>
          <div className="p-4 space-y-3">
            {[1, 2].map((i) => (
              <div key={i} className="flex items-center justify-between gap-3 rounded-xl p-3" style={{ background: "var(--rally-cobalt-soft)" }}>
                <div className="h-3 w-32 rounded shimmer" />
                <div className="h-5 w-16 rounded-full shimmer" />
              </div>
            ))}
          </div>
        </div>
        <Skeleton variant="block" height="10rem" className="rounded-2xl border border-rally-line" />
        <div className="rounded-2xl overflow-hidden" style={{ background: "white", border: "1px solid var(--rally-line)" }}>
          <div className="p-4 space-y-3">
            <div className="h-3 w-20 rounded shimmer" />
            <div className="h-11 w-full rounded-xl shimmer" />
            <div className="h-12 w-full rounded-xl shimmer" />
          </div>
        </div>
      </section>
    );
  }

  if (waiverQuery.isError || !waiver) {
    return (
      <section className="animate-fade-in-up">
        <div className="mb-4">
          <h1 className="font-display text-2xl font-bold tracking-tight" style={{ color: "var(--rally-ink)" }}>
            Waivers
          </h1>
        </div>
        <div
          className="rounded-2xl p-4 text-sm"
          style={{ background: "#fcebeb", border: "1px solid #f5c6c6", color: "#a32d2d" }}
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
          <h1 className="font-display text-2xl font-bold tracking-tight" style={{ color: "var(--rally-ink)" }}>
            Waivers
          </h1>
          <p className="text-sm mt-0.5" style={{ color: "var(--rally-muted)" }}>
            Liability &amp; consent forms
          </p>
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
        <h1 className="font-display text-2xl font-bold tracking-tight" style={{ color: "var(--rally-ink)" }}>
          {waiver.title ?? "Required waiver"}
        </h1>
        <p className="text-sm mt-0.5" style={{ color: "var(--rally-muted)" }}>
          Version {waiver.version ?? "current"}
        </p>
      </div>

      {/* Children status card */}
      <div
        className="rounded-2xl overflow-hidden"
        style={{ background: "white", border: "1px solid var(--rally-line)" }}
      >
        <div className="px-4 pt-4 pb-1">
          <p className="text-[10px] font-bold uppercase tracking-widest mb-2.5" style={{ color: "var(--rally-cobalt)" }}>
            Children
          </p>
        </div>
        <div className="px-4 pb-4 space-y-2">
          {waiver.students.map((student) => (
            <div
              key={student.student_id}
              className="flex items-center justify-between gap-3 rounded-xl px-3 py-2.5 text-sm"
              style={{ background: "var(--rally-cobalt-soft)" }}
            >
              <span className="font-medium truncate" style={{ color: "var(--rally-ink)" }}>
                {student.student_name}
              </span>
              <WaiverStatusPill status={student.status} />
            </div>
          ))}
        </div>
      </div>

      {/* Waiver body */}
      <article
        className="max-h-[360px] overflow-y-auto rounded-2xl p-4 text-sm leading-6"
        style={{
          background: "white",
          border: "1px solid var(--rally-line)",
          color: "var(--rally-ink)",
        }}
      >
        {waiver.body || "Waiver text is not available."}
      </article>

      {/* Signature / status card */}
      {needsSignature ? (
        <div
          className="rounded-2xl p-4"
          style={{ background: "white", border: "1px solid var(--rally-line)" }}
        >
          <label className="block text-sm font-medium" style={{ color: "var(--rally-ink)" }}>
            Signer name
            <input
              value={signerName}
              onChange={(event) => setSignerName(event.target.value)}
              className="mt-2 h-11 w-full rounded-xl px-3 text-sm outline-none transition-colors"
              style={{ border: "1px solid var(--rally-line)", color: "var(--rally-ink)" }}
              placeholder="Parent or guardian name"
            />
          </label>
          {acceptMutation.isError && (
            <p
              className="mt-3 rounded-xl px-3 py-2 text-sm"
              style={{ background: "#fcebeb", color: "#a32d2d" }}
              role="alert"
            >
              Could not accept waiver. Please try again.
            </p>
          )}
          {accepted && (
            <p
              className="mt-3 rounded-xl px-3 py-2 text-sm"
              style={{ background: "#e1f5ee", color: "#0f6e56" }}
              role="status"
            >
              Waiver accepted for your active child(ren).
            </p>
          )}
          <button
            type="button"
            onClick={() => acceptMutation.mutate()}
            disabled={acceptMutation.isPending}
            className="mt-4 min-h-touch w-full rounded-xl text-sm font-semibold disabled:opacity-60 active:scale-95 transition-transform"
            style={{
              background: "linear-gradient(135deg,#facc15,#f59e0b)",
              color: "#0a0f1c",
            }}
          >
            {acceptMutation.isPending ? "Accepting..." : "Accept waiver"}
          </button>
        </div>
      ) : (
        <div
          className="rounded-2xl p-4 text-sm"
          style={{ background: "#e1f5ee", border: "1px solid #b6e8d4", color: "#0f6e56" }}
        >
          Current waiver is signed for all active children.
        </div>
      )}
    </section>
  );
}

function WaiverStatusPill({ status }: { status: ParentWaiverStatus }) {
  const palette: Record<ParentWaiverStatus, { bg: string; color: string }> = {
    signed:       { bg: "#e1f5ee", color: "#0f6e56" },
    pending:      { bg: "#faeeda", color: "#854f0b" },
    outdated:     { bg: "#fcebeb", color: "#a32d2d" },
    not_required: { bg: "#f1efe8", color: "#5f5e5a" },
  };
  const { bg, color } = palette[status] ?? palette.not_required;
  return (
    <span
      className="shrink-0 inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold"
      style={{ background: bg, color }}
    >
      {waiverStatusLabel(status)}
    </span>
  );
}

function waiverStatusLabel(status: ParentWaiverStatus): string {
  if (status === "signed") return "Signed";
  if (status === "pending") return "Needed";
  if (status === "outdated") return "Outdated";
  return "Not required";
}
