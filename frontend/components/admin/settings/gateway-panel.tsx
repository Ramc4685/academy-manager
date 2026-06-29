"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  disconnectStripe,
  getAdminGateway,
  startStripeConnect,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import { Overline } from "@/components/ds/typography";

export function GatewayPanel() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const [connectError, setConnectError] = useState<string | null>(null);

  const stripeParam = searchParams.get("stripe");
  const justConnected = stripeParam === "connected";
  const connectFailed = stripeParam === "error";

  const query = useQuery({
    queryKey: queryKeys.admin.gateway(),
    queryFn: getAdminGateway,
  });
  const gateway = query.data;

  const connectMutation = useMutation({
    mutationFn: startStripeConnect,
    onSuccess: (data) => {
      window.location.href = data.url;
    },
    onError: () => {
      setConnectError("Could not start the connection. Please try again.");
    },
  });

  const disconnectMutation = useMutation({
    mutationFn: disconnectStripe,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.gateway() });
      const params = new URLSearchParams(searchParams.toString());
      params.delete("stripe");
      router.replace(`?${params.toString()}`);
    },
    onError: () => {
      setConnectError("Could not disconnect the account. Please try again.");
    },
  });

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
            {justConnected && (
              <p className="rounded-md bg-green-50 px-3 py-2 text-sm font-medium text-green-700">
                Stripe account connected successfully.
              </p>
            )}
            {connectFailed && (
              <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm font-medium text-red-700">
                Stripe Connect was not completed. Please try again.
              </p>
            )}
            {connectError && (
              <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm font-medium text-red-700">
                {connectError}
              </p>
            )}

            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="font-display text-[18px] font-semibold text-rally-ink">
                  Stripe Connect
                </p>
                <p className="mt-1 text-sm text-rally-muted">
                  {gateway?.stripe_connected
                    ? `Connected — ${gateway.stripe_account_id_masked ?? "account linked"}`
                    : "Connect your Stripe account to enable card payments for parents."}
                </p>
              </div>
              <Chip
                variant={gateway?.stripe_connected ? "enrolled" : "waitlist"}
                label={gateway?.stripe_connected ? "CONNECTED" : "NOT CONNECTED"}
              />
            </div>

            {gateway?.stripe_connected ? (
              <button
                onClick={() => disconnectMutation.mutate()}
                disabled={disconnectMutation.isPending}
                className="rounded-md border border-red-200 px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
              >
                {disconnectMutation.isPending ? "Disconnecting…" : "Disconnect Stripe"}
              </button>
            ) : (
              <button
                onClick={() => {
                  setConnectError(null);
                  connectMutation.mutate();
                }}
                disabled={connectMutation.isPending}
                className="inline-flex items-center gap-2 rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500 disabled:opacity-50"
              >
                {connectMutation.isPending ? "Redirecting…" : "Connect with Stripe"}
              </button>
            )}

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
