"use client";

import type { Route } from "next";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { ConfirmActionDialog } from "@/components/admin/confirm-action-dialog";
import { Button } from "@/components/ds/button";
import { ErrorNotice } from "@/components/ds/error-notice";
import { Skeleton } from "@/components/ds/skeleton";
import { CertificatePreview } from "@/components/progress/level-certificate";
import { getAdminAcademy } from "@/lib/api/admin";
import { getAdminCertificateDetail, revokeCertificate } from "@/lib/api/curriculum";
import { queryKeys } from "@/lib/query/keys";
import { useIsNativeApp } from "@/lib/use-native-app";

/** The same certificate a parent sees, for the front desk to print. */
export default function AdminCertificatePage() {
  const { studentId, certId } = useParams<{
    studentId: string;
    certId: string;
  }>();
  const isNativeApp = useIsNativeApp();
  const backHref = `/admin/students/${encodeURIComponent(studentId)}/progress` as Route;
  const detail = useQuery({
    queryKey: ["admin", "certificate", studentId, certId],
    queryFn: () => getAdminCertificateDetail(studentId, certId),
  });
  const academy = useQuery({
    queryKey: queryKeys.admin.academy(),
    queryFn: getAdminAcademy,
  });
  const queryClient = useQueryClient();
  const [confirmRevoke, setConfirmRevoke] = useState(false);
  const [reason, setReason] = useState("");
  const revoke = useMutation({
    mutationFn: () => revokeCertificate(studentId, certId, reason.trim()),
    onSuccess: () => {
      setConfirmRevoke(false);
      setReason("");
      void queryClient.invalidateQueries({ queryKey: ["admin", "certificate", studentId, certId] });
      void queryClient.invalidateQueries({ queryKey: ["admin", "student-certificates", studentId] });
    },
  });
  const cert = detail.data?.certificate;
  const revoked = cert?.status === "revoked";

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
            <div className="flex flex-wrap gap-2">
              {!revoked && (
                <Button variant="secondary" onClick={() => setConfirmRevoke(true)}>
                  Revoke
                </Button>
              )}
              {!isNativeApp && !revoked && (
                <Button onClick={() => window.print()}>Print or save as PDF</Button>
              )}
            </div>
          </div>
          {revoked && (
            <p
              role="status"
              data-testid="certificate-revoked-banner"
              className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800"
            >
              Revoked
              {cert?.revoked_at ? ` on ${new Date(cert.revoked_at).toLocaleDateString()}` : ""}
              {cert?.revoke_reason ? `: ${cert.revoke_reason}` : ""}. The family no longer sees this
              certificate.
            </p>
          )}
          <ConfirmActionDialog
            open={confirmRevoke}
            onOpenChange={(next) => {
              setConfirmRevoke(next);
              if (!next) revoke.reset();
            }}
            overline="Revoke certificate"
            title={`Revoke ${detail.data.certificate.cert_number}?`}
            subject={`${detail.data.certificate.student_name}: ${detail.data.certificate.level_name}`}
            consequence="The family stops seeing it and any share link stops working. The student stays on their current level; if they earn this level again, a new certificate is issued."
            confirmLabel="Revoke certificate"
            pending={revoke.isPending}
            reason={{
              label: "Reason",
              value: reason,
              onChange: setReason,
              required: true,
              placeholder: "Approved by mistake",
            }}
            error={revoke.isError ? revoke.error.message || "Could not revoke it." : null}
            onConfirm={() => revoke.mutate()}
          />
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
