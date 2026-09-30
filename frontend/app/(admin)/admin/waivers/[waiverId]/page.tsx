"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { getAdminWaiverTemplate } from "@/lib/api/admin";
import { Card, LaneHeader, Overline } from "@/components/ds";

export default function AdminWaiverTemplateDetailPage() {
  const params = useParams<{ waiverId: string }>();
  const waiverId = decodeURIComponent(params.waiverId);
  const detailQueryKey = ["admin", "waivers", "template", waiverId] as const;

  const waiverQuery = useQuery({
    queryKey: detailQueryKey,
    queryFn: () => getAdminWaiverTemplate(waiverId),
    retry: false,
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
          <LaneHeader index="01" title="Waiver template" />
          <Card p={24}>
            <Overline>Version {waiverQuery.data.version || "not reported"}</Overline>
            <h1 className="mt-2 font-display text-2xl font-semibold text-rally-ink">
              {waiverQuery.data.title}
            </h1>
            <dl className="mt-5 grid gap-4 border-t border-neutral-100 pt-4 sm:grid-cols-3">
              <Meta label="Status" value={waiverQuery.data.status.toUpperCase()} />
              <Meta label="Effective" value={formatDate(waiverQuery.data.effective_at)} />
              <Meta label="Artifact" value={statusLabel(waiverQuery.data.artifact_status)} />
              <Meta label="Share link" value={statusLabel(waiverQuery.data.share_status)} />
            </dl>
          </Card>

          <LaneHeader index="02" title="Who signs this waiver" />
          <Card p={20}>
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <Overline>Family policies</Overline>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-rally-muted">
                  {waiverQuery.data.status === "active"
                    ? "Choose whether this waiver is required, and for all families or only families in certain programs."
                    : "Publish the draft before choosing who signs it."}
                </p>
              </div>
              {waiverQuery.data.status === "active" && (
                <Link
                  href="/admin/settings?panel=family-policies"
                  data-testid="admin-waiver-detail-assign-link"
                  className="inline-flex min-h-touch items-center justify-center rounded-md bg-rally-ink px-3 py-2 text-sm font-semibold text-white"
                >
                  Assign in Family policies
                </Link>
              )}
            </div>
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
