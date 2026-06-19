"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import {
  getCoachProfile,
  updateCoachProfile,
  type UpdateCoachProfileRequest,
} from "@/lib/api/coach";
import { queryKeys } from "@/lib/query/keys";
import { PersonaLogoutButton } from "@/components/persona/logout-button";

export default function CoachProfilePage() {
  const queryClient = useQueryClient();

  const { data: profile, isLoading } = useQuery({
    queryKey: queryKeys.coach.profile(),
    queryFn: getCoachProfile,
    staleTime: 5 * 60 * 1000,
  });

  const [editing, setEditing] = useState(false);
  const [displayName, setDisplayName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [saveError, setSaveError] = useState<string | null>(null);

  function startEditing() {
    setDisplayName(profile?.display_name ?? "");
    setPhone(profile?.phone ?? "");
    setEmail(profile?.email ?? "");
    setSaveError(null);
    setEditing(true);
  }

  const mutation = useMutation({
    mutationFn: (payload: UpdateCoachProfileRequest) => updateCoachProfile(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.coach.profile() });
      setEditing(false);
      setSaveError(null);
    },
    onError: (err: Error) => {
      setSaveError(err.message ?? "Failed to save. Please try again.");
    },
  });

  function handleSave() {
    const payload: UpdateCoachProfileRequest = {};
    if (displayName.trim() && displayName.trim() !== profile?.display_name) {
      payload.display_name = displayName.trim();
    }
    if (phone.trim() !== (profile?.phone ?? "")) {
      payload.phone = phone.trim() || null;
    }
    if (email.trim() && email.trim() !== profile?.email) {
      payload.email = email.trim();
    }
    if (Object.keys(payload).length === 0) {
      setEditing(false);
      return;
    }
    mutation.mutate(payload);
  }

  return (
    <section data-testid="coach-profile">
      <header className="mb-4">
        <h1 className="text-2xl font-semibold">Profile</h1>
        <p className="text-sm text-neutral-500">Coach access</p>
      </header>

      {isLoading && <p className="text-neutral-500">Loading profile...</p>}

      {!isLoading && profile && !editing && (
        <div className="space-y-4">
          <div className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900">
            <dl className="space-y-3">
              <div>
                <dt className="text-sm text-neutral-500">Name</dt>
                <dd className="mt-0.5 font-medium">{profile.display_name}</dd>
              </div>
              <div>
                <dt className="text-sm text-neutral-500">Email</dt>
                <dd className="mt-0.5 font-medium">{profile.email}</dd>
              </div>
              <div>
                <dt className="text-sm text-neutral-500">Phone</dt>
                <dd className="mt-0.5 font-medium">{profile.phone ?? "—"}</dd>
              </div>
            </dl>
            <button
              onClick={startEditing}
              className="mt-4 min-h-touch rounded-md border border-neutral-300 px-4 text-sm font-medium text-neutral-800 hover:bg-neutral-50 dark:border-neutral-700 dark:text-neutral-100 dark:hover:bg-neutral-900"
            >
              Edit
            </button>
          </div>

          <section className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900">
            <h2 className="font-semibold">Pay &amp; statements</h2>
            <p className="mt-1 text-sm text-neutral-500">
              Pay information lives here, separate from Coach Home.
            </p>
            <p className="mt-3 rounded-md bg-neutral-50 p-3 text-sm text-neutral-600 dark:bg-neutral-800">
              Statement downloads are not available in this workspace yet.
            </p>
          </section>
        </div>
      )}

      {!isLoading && editing && (
        <div className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900">
          <div className="space-y-4">
            <div>
              <label className="block text-sm text-neutral-500" htmlFor="displayName">
                Name
              </label>
              <input
                id="displayName"
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                className="mt-1 w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-neutral-700 dark:bg-neutral-900"
              />
            </div>
            <div>
              <label className="block text-sm text-neutral-500" htmlFor="email">
                Email
              </label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="mt-1 w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-neutral-700 dark:bg-neutral-900"
              />
            </div>
            <div>
              <label className="block text-sm text-neutral-500" htmlFor="phone">
                Phone
              </label>
              <input
                id="phone"
                type="tel"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="e.g. 309-531-0000"
                className="mt-1 w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-neutral-700 dark:bg-neutral-900"
              />
            </div>
          </div>

          {saveError && (
            <p className="mt-3 text-sm text-red-600 dark:text-red-400">{saveError}</p>
          )}

          <div className="mt-4 flex gap-3">
            <button
              onClick={handleSave}
              disabled={mutation.isPending}
              className="min-h-touch rounded-md bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {mutation.isPending ? "Saving…" : "Save"}
            </button>
            <button
              onClick={() => setEditing(false)}
              disabled={mutation.isPending}
              className="min-h-touch rounded-md border border-neutral-300 px-4 text-sm font-medium text-neutral-800 hover:bg-neutral-50 disabled:opacity-50 dark:border-neutral-700 dark:text-neutral-100"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      <PersonaLogoutButton className="mt-4 min-h-touch rounded-md border border-neutral-300 px-4 text-sm font-medium text-neutral-800 hover:bg-neutral-50 dark:border-neutral-700 dark:text-neutral-100 dark:hover:bg-neutral-900" />
    </section>
  );
}
