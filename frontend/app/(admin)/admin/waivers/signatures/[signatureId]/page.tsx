"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { getAdminWaiverSignature } from "@/lib/api/admin";
import { Card, LaneHeader, Overline } from "@/components/ds";

export default function AdminSignedWaiverDetailPage() {
  const params = useParams<{ signatureId: string }>();
  const signatureId = decodeURIComponent(params.signatureId);

  const signatureQuery = useQuery({
    queryKey: ["admin", "waivers", "signature", signatureId],
    queryFn: () => getAdminWaiverSignature(signatureId),
    retry: false,
  });

  return (
    <section data-testid="admin-signed-waiver-detail" className="space-y-5">
      <Link href="/admin/waivers" className="text-sm font-semibold text-rally-cobalt hover:underline">
        Back to waivers
      </Link>

      {signatureQuery.isPending && <Card p={20}>Loading signed waiver...</Card>}

      {signatureQuery.isError && (
        <Card p={16} style={{ borderColor: "#fecaca", background: "#fef2f2" }}>
          <p role="alert" className="text-sm text-red-800">Could not load signed waiver.</p>
        </Card>
      )}

      {signatureQuery.data && (
        <>
          <LaneHeader index="01" title="Signed waiver" />
          <Card p={24}>
            <Overline>{signatureQuery.data.waiver_title || "Waiver record"}</Overline>
            <h1 className="mt-2 font-display text-2xl font-semibold text-rally-ink">
              {signatureQuery.data.student_name}
            </h1>
            <dl className="mt-5 grid gap-4 border-t border-neutral-100 pt-4 sm:grid-cols-3">
              <Meta label="Signed" value={formatDate(signatureQuery.data.signed_at)} />
              <Meta label="Version" value={signatureQuery.data.waiver_version || "Not reported"} />
              <Meta label="Template" value={signatureQuery.data.waiver_title || "Not reported"} />
            </dl>
          </Card>

          <LaneHeader index="02" title="Signer and artifact status" />
          <Card p={20}>
            <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Meta label="Parent" value={signatureQuery.data.parent_name || "Not reported"} />
              <Meta label="Parent email" value={signatureQuery.data.parent_email || "Not reported"} />
              <Meta label="Signer" value={signatureQuery.data.signer_name || "Not reported"} />
              <Meta label="Artifact" value={statusLabel(signatureQuery.data.artifact_status)} />
              <Meta label="Share link" value={statusLabel(signatureQuery.data.share_status)} />
              <Meta label="Artifact ref" value={signatureQuery.data.artifact_reference || "Not stored"} />
              <Meta label="Share ref" value={signatureQuery.data.share_link_reference || "Not stored"} />
            </dl>
          </Card>

          <Card p={16} style={{ borderColor: "#fed7aa", background: "#fff7ed" }}>
            <p className="text-sm text-orange-900">{signatureQuery.data.gap_note}</p>
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
