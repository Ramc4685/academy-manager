"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  acceptParentWaiver,
  getParentCurrentWaiver,
  type ParentWaiverStatus,
} from "@/lib/api/parent";

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
    return <p className="text-sm text-neutral-500">Loading waiver...</p>;
  }

  if (waiverQuery.isError || !waiver) {
    return <p className="text-sm text-red-600">Could not load waiver.</p>;
  }

  if (!waiver.required) {
    return (
      <section data-testid="parent-waivers" className="space-y-4">
        <h1 className="text-2xl font-semibold">Waivers</h1>
        <p className="text-sm text-neutral-600">No waiver is required right now.</p>
      </section>
    );
  }

  return (
    <section data-testid="parent-waivers" className="space-y-5">
      <header>
        <h1 className="text-2xl font-semibold">{waiver.title ?? "Required waiver"}</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Version {waiver.version ?? "current"}
        </p>
      </header>

      <div className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900">
        <h2 className="font-semibold">Children</h2>
        <div className="mt-3 space-y-2">
          {waiver.students.map((student) => (
            <div
              key={student.student_id}
              className="flex items-center justify-between gap-3 rounded-md bg-neutral-50 px-3 py-2 text-sm dark:bg-neutral-800"
            >
              <span>{student.student_name}</span>
              <span className="font-mono text-[11px] font-bold">
                {waiverStatusLabel(student.status)}
              </span>
            </div>
          ))}
        </div>
      </div>

      <article className="max-h-[360px] overflow-y-auto rounded-lg border border-neutral-200 bg-white p-4 text-sm leading-6 text-neutral-700 dark:border-neutral-800 dark:bg-neutral-900 dark:text-neutral-200">
        {waiver.body || "Waiver text is not available."}
      </article>

      {needsSignature ? (
        <div className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900">
          <label className="block text-sm font-medium">
            Signer name
            <input
              value={signerName}
              onChange={(event) => setSignerName(event.target.value)}
              className="mt-2 h-10 w-full rounded-md border border-neutral-200 px-3 text-sm outline-none focus:border-blue-600"
              placeholder="Parent or guardian name"
            />
          </label>
          {acceptMutation.isError && (
            <p className="mt-3 text-sm text-red-600">Could not accept waiver.</p>
          )}
          {accepted && (
            <p className="mt-3 text-sm text-emerald-700" role="status">
              Waiver accepted for your active child(ren).
            </p>
          )}
          <button
            type="button"
            onClick={() => acceptMutation.mutate()}
            disabled={acceptMutation.isPending}
            className="mt-4 min-h-touch w-full rounded-md bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
          >
            {acceptMutation.isPending ? "Accepting..." : "Accept waiver"}
          </button>
        </div>
      ) : (
        <p className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">
          Current waiver is signed for all active children.
        </p>
      )}
    </section>
  );
}

function waiverStatusLabel(status: ParentWaiverStatus): string {
  if (status === "signed") return "SIGNED";
  if (status === "pending") return "NEEDED";
  if (status === "outdated") return "OUTDATED";
  return "NOT REQUIRED";
}
