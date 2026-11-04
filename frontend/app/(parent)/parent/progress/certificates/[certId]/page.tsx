"use client";

import type { Route } from "next";
import { Suspense } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ErrorNotice } from "@/components/ds/error-notice";
import { Skeleton } from "@/components/ds/skeleton";
import { getParentCertificateDetail } from "@/lib/api/curriculum";
import { getParentAcademy } from "@/lib/api/parent";
import { queryKeys } from "@/lib/query/keys";
import { CertificateScreen, shareCertificate } from "./certificate-screen";

export default function ParentCertificatePage() {
  return (
    <Suspense fallback={<CertificateSkeleton />}>
      <ParentCertificate />
    </Suspense>
  );
}

function ParentCertificate() {
  const { certId } = useParams<{ certId: string }>();
  // Every link here (progress page, journey wins, evening email) carries the
  // child: the API checks the certificate belongs to that child.
  const studentId = useSearchParams().get("child") ?? "";
  const progressHref = (
    studentId ? `/parent/progress?child=${encodeURIComponent(studentId)}` : "/parent/progress"
  ) as Route;

  const detail = useQuery({
    queryKey: ["parent", "certificate", studentId, certId],
    queryFn: () => getParentCertificateDetail(studentId, certId),
    enabled: Boolean(studentId && certId),
  });
  const academy = useQuery({
    queryKey: queryKeys.parent.academy(),
    queryFn: getParentAcademy,
  });

  if (!studentId || detail.isError) {
    return (
      <div className="mx-auto max-w-xl space-y-3">
        <ErrorNotice
          message="We couldn't find this certificate."
          onRetry={studentId ? () => void detail.refetch() : undefined}
          retrying={detail.isFetching}
        />
        <Link href={progressHref} className="text-sm font-bold text-rally-cobalt-700">
          Back to progress
        </Link>
      </div>
    );
  }
  if (detail.isLoading || academy.isLoading || !detail.data) return <CertificateSkeleton />;

  const brand = academy.data;
  return (
    <CertificateScreen
      detail={detail.data}
      academy={{
        name: brand?.display_name ?? "",
        logoUrl: brand?.logo_url,
        brandColor: brand?.brand_color,
        timezone: brand?.timezone,
      }}
      progressHref={progressHref}
      onPrint={() => window.print()}
      onShare={() => void shareCertificate(detail.data, brand?.display_name ?? "")}
    />
  );
}

function CertificateSkeleton() {
  return (
    <div className="mx-auto max-w-xl space-y-4">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-16 w-full" />
      <Skeleton className="aspect-[1056/816] w-full" />
    </div>
  );
}
