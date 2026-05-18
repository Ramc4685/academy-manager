"use client";

import { useQuery } from "@tanstack/react-query";

import { getCurrentUser } from "@/lib/api/me";

export default function AdminSettingsPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["me", "settings"],
    queryFn: getCurrentUser,
  });

  return (
    <section data-testid="admin-settings" className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">Settings</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Academy identity and operator safety state for the v2 local app.
        </p>
      </div>

      {isError ? (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load settings.
        </p>
      ) : isLoading ? (
        <div className="h-32 animate-pulse rounded-lg bg-neutral-100 dark:bg-neutral-800" />
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          <Setting label="Academy ID" value={data?.academy_id ?? "-"} />
          <Setting label="Signed in as" value={data?.email ?? "-"} />
          <Setting label="Roles" value={(data?.roles ?? []).join(", ") || "-"} />
          <Setting label="Email sending" value="Blocked in local/dev" />
          <Setting label="Stripe mode" value="Fake gateway in local/dev" />
          <Setting label="Auth source" value="Firebase Authentication" />
        </div>
      )}
    </section>
  );
}

function Setting({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900">
      <p className="text-xs font-medium uppercase tracking-wide text-neutral-500">{label}</p>
      <p className="mt-2 break-words font-medium">{value}</p>
    </div>
  );
}
