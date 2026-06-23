"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  assignAdminWaiverTemplateToRegistration,
  getAdminWaiverTemplate,
  type AdminWaiverTemplateDetail,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Card, LaneHeader, Overline } from "@/components/ds";

export default function AdminWaiverTemplateDetailPage() {
  const queryClient = useQueryClient();
  const params = useParams<{ waiverId: string }>();
  const waiverId = decodeURIComponent(params.waiverId);
  const detailQueryKey = ["admin", "waivers", "template", waiverId] as const;

  const waiverQuery = useQuery({
    queryKey: detailQueryKey,
    queryFn: () => getAdminWaiverTemplate(waiverId),
    retry: false,
  });

  const assignMutation = useMutation({
    mutationFn: () => assignAdminWaiverTemplateToRegistration(waiverId),
    onSuccess: (template) => {
      queryClient.setQueryData<AdminWaiverTemplateDetail>(detailQueryKey, (current) => {
        if (!current) return current;
        return {
          ...current,
          assigned_to_registration: template.assigned_to_registration,
          assigned_at: template.assigned_at,
        };
      });
      void queryClient.invalidateQueries({ queryKey: detailQueryKey });
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.waiverTemplates() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.waivers() });
    },
  });

  return (
    <section data-testid="admin-waiver-template-detail" className="space-y-5">
      <Link href="/admin/waivers" className="text-sm font-semibold text-rally-cobalt hover:underline">
        Back to waivers
      </Link>

      {waiverQuery.isPending && <Card p={20}>Loading waiver template...</Card>}

      {waiverQuery.isError && !waiverQuery.data && (
        <Card p={16} style={{ borderColor: "#fecaca", background: "#fef2f2" }}>
          <p role="alert" className="text-sm text-red-800">Could not load waiver template.</p>
        </Card>
      )}

      {waiverQuery.data && (
        <>
          {(() => {
            const assignedToRegistration =
              assignMutation.data?.assigned_to_registration ??
              waiverQuery.data.assigned_to_registration;
            const assignedAt =
              assignMutation.data?.assigned_at ?? waiverQuery.data.assigned_at;
            const canAssign =
              waiverQuery.data.status === "active" &&
              !assignedToRegistration &&
              !assignMutation.isPending;

            return (
              <>
          <LaneHeader index="01" title="Waiver template" />
          <Card p={24}>
            <Overline>Version {waiverQuery.data.version || "not reported"}</Overline>
            <h1 className="mt-2 font-display text-2xl font-semibold text-rally-ink">
              {waiverQuery.data.title}
            </h1>
            <dl className="mt-5 grid gap-4 border-t border-neutral-100 pt-4 sm:grid-cols-3">
              <Meta label="Status" value={waiverQuery.data.status.toUpperCase()} />
              <Meta label="Effective" value={formatDate(waiverQuery.data.effective_at)} />
              <Meta
                label="Registration"
                value={assignedToRegistration ? "Required for registration" : "Not assigned"}
              />
              {assignedToRegistration && (
                <Meta label="Assigned" value={formatDate(assignedAt)} />
              )}
              <Meta label="Artifact" value={statusLabel(waiverQuery.data.artifact_status)} />
              <Meta label="Share link" value={statusLabel(waiverQuery.data.share_status)} />
            </dl>
          </Card>

          <LaneHeader index="02" title="Registration assignment" />
          <Card p={20}>
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <Overline>Parent onboarding</Overline>
                <p className="mt-2 text-sm font-semibold text-rally-ink">
                  {assignedToRegistration
                    ? "Required for registration"
                    : "Not assigned"}
                </p>
                <p className="mt-1 max-w-2xl text-sm leading-6 text-rally-muted">
                  {waiverQuery.data.status === "active"
                    ? "This controls the waiver shown during parent registration."
                    : "Publish the draft before assigning it to parent registration."}
                </p>
              </div>
              {!assignedToRegistration && (
                <button
                  type="button"
                  onClick={() => assignMutation.mutate()}
                  disabled={!canAssign}
                  className="inline-flex min-h-touch items-center justify-center rounded-md bg-rally-ink px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {assignMutation.isPending ? "Assigning..." : "Require for registration"}
                </button>
              )}
            </div>
            {assignMutation.isError && (
              <p role="alert" className="mt-3 text-sm text-red-700">
                Could not assign this waiver to registration.
              </p>
            )}
          </Card>

          <LaneHeader index="03" title="Template text" />
          <Card p={20}>
            {waiverQuery.data.body ? (
              <pre className="whitespace-pre-wrap text-sm leading-6 text-rally-base">
                {waiverQuery.data.body}
              </pre>
            ) : (
              <p className="text-sm text-rally-subtle">Template text is not stored for this waiver record.</p>
            )}
          </Card>

          <LaneHeader index="04" title="Editing" />
          <Card p={16}>
            <p className="text-sm leading-6 text-rally-muted">
              Published waiver text is locked to preserve what parents signed. Create a new
              draft from Waivers when the wording needs to change.
            </p>
          </Card>

          <Card p={16} style={{ borderColor: "#fed7aa", background: "#fff7ed" }}>
            <p className="text-sm text-orange-900">{waiverQuery.data.gap_note}</p>
          </Card>
              </>
            );
          })()}
        </>
      )}
    </section>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <Overline>{label}</Overline>
      <dd className="mt-1 text-sm font-semibold text-rally-ink">{value}</dd>
    </div>
  );
}

function statusLabel(status: string): string {
  if (status === "stored") return "Stored";
  if (status === "available") return "Available";
  if (status === "stored_reference") return "Stored reference";
  return "Unavailable";
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "Not reported";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "2-digit",
    year: "numeric",
  }).format(new Date(value));
}
