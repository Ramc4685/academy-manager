"use client";

import { useQuery } from "@tanstack/react-query";

import { getAdminGateway } from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import { Overline } from "@/components/ds/typography";

export function GatewayPanel() {
  const query = useQuery({
    queryKey: queryKeys.admin.gateway(),
    queryFn: getAdminGateway,
  });
  const gateway = query.data;

  return (
    <section data-testid="admin-settings-gateway" className="space-y-4">
      <Card p={24} className="max-w-3xl">
        <Overline>Gateway</Overline>
        {query.isLoading ? (
          <div className="mt-5 h-24 animate-pulse rounded-md bg-rally-paper" />
        ) : query.isError ? (
          <p role="alert" className="mt-4 text-sm font-medium text-red-700">
            Could not load gateway status.
          </p>
        ) : (
          <div className="mt-5 space-y-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="font-display text-[18px] font-semibold text-rally-ink">
                  Stripe Connect
                </p>
                <p className="mt-1 text-sm text-rally-muted">
                  {gateway?.stripe_connected
                    ? `Connected account ${gateway.stripe_account_id_masked ?? ""}`.trim()
                    : "Not connected. Onboarding writes are a separate workstream."}
                </p>
              </div>
              <Chip
                variant={gateway?.stripe_connected ? "enrolled" : "manual"}
                label={gateway?.stripe_connected ? "CONNECTED" : "DEFERRED"}
              />
            </div>
            <div>
              <p className="mb-2 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                Manual methods
              </p>
              <div className="flex flex-wrap gap-2">
                {(gateway?.manual_methods ?? []).map((method) => (
                  <Chip key={method} variant="manual" label={method.toUpperCase()} />
                ))}
              </div>
            </div>
          </div>
        )}
      </Card>
    </section>
  );
}
