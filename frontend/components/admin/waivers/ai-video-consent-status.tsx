"use client";

import { useQuery } from "@tanstack/react-query";

import { Card, Chip } from "@/components/ds";
import { listAdminAiVideoConsents } from "@/lib/api/admin";
import type { AiVideoConsentRow } from "@/lib/api/parent";
import { queryKeys } from "@/lib/query/keys";

/** Read-only per-child AI/video consent status (Phase 3 E1). Parents grant and revoke. */
export function AiVideoConsentStatus() {
  const query = useQuery({
    queryKey: queryKeys.admin.aiVideoConsents(),
    queryFn: () => listAdminAiVideoConsents(),
    retry: false,
  });
  if (query.isError) return null;
  return <AiVideoConsentStatusList rows={query.data?.children ?? []} />;
}

const STATUS_CHIP = {
  granted: { variant: "approved", label: "Opted in" },
  revoked: { variant: "expired", label: "Revoked" },
  none: { variant: "expired", label: "Not opted in" },
} as const;

export function AiVideoConsentStatusList({ rows }: { rows: AiVideoConsentRow[] }) {
  return (
    <Card p={0} data-testid="admin-ai-video-consents">
      <p className="px-5 pt-4 text-xs text-rally-subtle">
        Optional, set by parents. The consent text is a draft awaiting counsel, so no consent
        authorizes video analysis yet.
      </p>
      {rows.length === 0 ? (
        <p className="p-5 text-sm text-rally-subtle">No parent has opted a child in.</p>
      ) : (
        <ul className="divide-y divide-rally-line p-2">
          {rows.map((row) => {
            const chip = STATUS_CHIP[row.status];
            const when = row.status === "revoked" ? row.revoked_at : row.accepted_at;
            return (
              <li key={row.student_id} className="flex items-center justify-between gap-3 px-3 py-2.5 text-sm">
                <span className="font-medium text-rally-ink">{row.student_name}</span>
                <span className="flex items-center gap-2 text-xs text-rally-subtle">
                  {when && <span>{new Date(when).toLocaleDateString()}</span>}
                  {row.text_version && <span>{row.text_version}</span>}
                  <Chip variant={chip.variant} label={chip.label} />
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
