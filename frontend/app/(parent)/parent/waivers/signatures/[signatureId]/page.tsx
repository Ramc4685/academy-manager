"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { Skeleton } from "@/components/ds/skeleton";
import { SignedWaiverDocument } from "@/components/waivers/signed-waiver-document";
import { getParentSignedWaiver } from "@/lib/api/parent";

export default function ParentSignedWaiverPage() {
  const params = useParams<{ signatureId: string }>();
  const signatureId = decodeURIComponent(params.signatureId);
  const copyQuery = useQuery({
    queryKey: ["parent", "waivers", "signature", signatureId],
    queryFn: () => getParentSignedWaiver(signatureId),
    retry: false,
  });

  return (
    <section data-testid="parent-signed-waiver" className="space-y-4 animate-fade-in-up">
      <Link
        href="/parent/waivers"
        className="text-sm font-semibold text-rally-cobalt-600 hover:underline print:hidden"
      >
        Back to waivers
      </Link>
      {copyQuery.isPending && <Skeleton variant="block" height="24rem" className="rounded-2xl" />}
      {copyQuery.isError && (
        <div
          className="rounded-2xl p-4 text-sm bg-status-red-50 border border-status-red-200 text-status-red-800"
          role="alert"
        >
          Could not load this signed waiver. It may not be yours, or it may have been removed.
        </div>
      )}
      {copyQuery.data && <SignedWaiverDocument copy={copyQuery.data} />}
    </section>
  );
}
