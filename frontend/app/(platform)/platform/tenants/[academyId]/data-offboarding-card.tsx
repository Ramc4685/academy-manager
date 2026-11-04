"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { Button, Card, FormField, Modal, Overline, useToast } from "@/components/ds";
import {
  exportPlatformTenantData,
  previewPlatformTenantPurge,
  type PlatformTenant,
  type PurgeDryRun,
} from "@/lib/api/platform";

/**
 * Tenant data export and purge dry-run (roadmap L9d). Platform admin only.
 *
 * Export downloads a zip of every tenant-scoped collection for this academy
 * and is audit logged. The purge preview is only offered for a cancelled
 * tenant and deletes nothing: an actual purge is run by hand after the owner
 * confirms (docs/runbooks/tenant-export-and-purge.md).
 */
export function DataOffboardingCard({ tenant }: { tenant: PlatformTenant }) {
  const { toast } = useToast();
  const [exporting, setExporting] = useState(false);
  const cancelled = tenant.status === "cancelled";

  const preview = useMutation({
    mutationFn: () => previewPlatformTenantPurge(tenant.academy_id),
    onError: (err: Error) => {
      toast({ kind: "error", title: "Could not preview the purge", description: err.message });
    },
  });

  return (
    <Card p={20}>
      <div data-testid="platform-tenant-data-offboarding">
        <Overline>Data export and purge</Overline>
        <p className="mt-2 text-sm text-rally-subtle">
          Export downloads every record this academy owns as a zip. Each export is recorded in the
          platform audit log.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button variant="secondary" size="sm" onClick={() => setExporting(true)}>
            Export data
          </Button>
          <Button
            variant="secondary"
            size="sm"
            disabled={!cancelled || preview.isPending}
            onClick={() => preview.mutate()}
          >
            {preview.isPending ? "Counting…" : "Preview purge"}
          </Button>
        </div>
        {!cancelled && (
          <p className="mt-2 text-xs text-rally-subtle">
            A purge can only be previewed once the tenant is cancelled.
          </p>
        )}
        {preview.data && <PurgePreview result={preview.data} />}
      </div>
      {exporting && <ExportDialog tenant={tenant} onClose={() => setExporting(false)} />}
    </Card>
  );
}

function PurgePreview({ result }: { result: PurgeDryRun }) {
  return (
    <div className="mt-4 space-y-3" data-testid="purge-dry-run-result">
      <p className="rounded-lg bg-status-amber-50 px-3 py-2 text-sm text-status-amber-800">
        Preview only. Nothing was deleted. A purge of{" "}
        <strong>{result.total_to_delete.toLocaleString()}</strong> records needs the owner&apos;s
        confirmation and this token: <code className="break-all">{result.confirm_token}</code>
      </p>
      <CountTable caption="Would be deleted" rows={result.would_delete} />
      <CountTable caption="Would be kept" rows={result.would_retain} />
    </div>
  );
}

function CountTable({
  caption,
  rows,
}: {
  caption: string;
  rows: PurgeDryRun["would_delete"];
}) {
  return (
    <table className="w-full text-sm">
      <caption className="text-left text-xs font-semibold uppercase tracking-wide text-rally-subtle">
        {caption}
      </caption>
      <thead className="sr-only">
        <tr>
          <th scope="col">Collection</th>
          <th scope="col">Records</th>
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 ? (
          <tr>
            <td className="py-1 text-rally-subtle" colSpan={2}>
              None
            </td>
          </tr>
        ) : (
          rows.map((row) => (
            <tr key={row.collection} className="border-t border-rally-line">
              <td className="py-1 font-mono text-rally-ink">{row.collection}</td>
              <td className="py-1 text-right tabular-nums text-rally-ink">
                {row.count.toLocaleString()}
              </td>
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
}

function ExportDialog({ tenant, onClose }: { tenant: PlatformTenant; onClose: () => void }) {
  const { toast } = useToast();
  const [reason, setReason] = useState("");

  const mutation = useMutation({
    mutationFn: () => exportPlatformTenantData(tenant.academy_id, reason.trim()),
    onSuccess: (blob) => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `tenant-export-${tenant.academy_id}.zip`;
      a.click();
      URL.revokeObjectURL(url);
      toast({ kind: "success", title: "Export downloaded" });
      onClose();
    },
    onError: (err: Error) => {
      toast({ kind: "error", title: "Could not export data", description: err.message });
    },
  });

  return (
    <Modal
      open
      onClose={onClose}
      title="Export academy data"
      dismissable={!mutation.isPending}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button
            size="sm"
            disabled={reason.trim().length === 0 || mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending ? "Exporting…" : "Download export"}
          </Button>
        </div>
      }
    >
      <p className="text-sm text-rally-subtle">
        The file holds families, students, payments and every other record for{" "}
        {tenant.display_name}. Store it somewhere private.
      </p>
      <div className="mt-3">
        <FormField
          label="Reason"
          htmlFor="tenant-export-reason"
          hint="Saved in the platform audit log."
          required
        >
          <input
            id="tenant-export-reason"
            maxLength={500}
            className="w-full rounded-lg border border-rally-line bg-white px-3 py-2 text-sm text-rally-ink outline-none focus:border-rally-cobalt"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </FormField>
      </div>
    </Modal>
  );
}
