"use client";

import type { Route } from "next";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ds/button";
import { ErrorNotice } from "@/components/ds/error-notice";
import { Skeleton } from "@/components/ds/skeleton";
import { CertificatePreview } from "@/components/progress/level-certificate";
import { getAdminAcademy } from "@/lib/api/admin";
import { getAdminCertificateDetail } from "@/lib/api/curriculum";
import { queryKeys } from "@/lib/query/keys";

/** The same certificate a parent sees, for the front desk to print. */
export default function AdminCertificatePage() {
  const { studentId, certId } = useParams<{
    studentId: string;
    certId: string;
  }>();
  const backHref = `/admin/students/${encodeURIComponent(studentId)}/progress` as Route;
  const detail = useQuery({
    queryKey: ["admin", "certificate", studentId, certId],
    queryFn: () => getAdminCertificateDetail(studentId, certId),
  });
  const academy = useQuery({
    queryKey: queryKeys.admin.academy(),
    queryFn: getAdminAcademy,
  });

  return (
    <section className="mx-auto max-w-4xl space-y-4" data-testid="admin-certificate">
      <Link
        href={backHref}
        className="inline-flex items-center gap-1.5 text-sm font-semibold text-rally-cobalt-700"
      >
        <ArrowLeft aria-hidden="true" className="h-4 w-4" />
        Back to progress
      </Link>
      {detail.isError ? (
        <ErrorNotice
          message="Could not load this certificate."
          onRetry={() => void detail.refetch()}
          retrying={detail.isFetching}
        />
      ) : detail.isLoading || academy.isLoading || !detail.data ? (
        <Skeleton className="aspect-[1056/816] w-full" />
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h1 className="font-display text-xl font-bold text-rally-ink">
              {detail.data.certificate.student_name}: {detail.data.certificate.level_name}
            </h1>
            <Button onClick={() => window.print()}>Print or save as PDF</Button>
          </div>
          <CertificatePreview
            detail={detail.data}
            academy={{
              name: academy.data?.display_name ?? "",
              logoUrl: academy.data?.logo_url,
              brandColor: academy.data?.brand_color,
              timezone: academy.data?.timezone,
            }}
          />
        </>
      )}
    </section>
  );
}
