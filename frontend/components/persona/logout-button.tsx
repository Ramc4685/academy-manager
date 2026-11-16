"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { LogOut } from "lucide-react";

import { signOutCurrent } from "@/lib/auth/firebase";
import { clearAll as clearOfflineQueue, list as listAllMutations } from "@/lib/offline/queue";
import { clearPersistedQueryCache } from "@/lib/query/persistence";

/** The service worker's coach read cache (app/sw.ts). */
const COACH_SW_CACHE = "coach-api-v1";

/** Everything sign-out would delete: queued, in-flight and Needs-review marks. */
export async function unsentMarkCount(): Promise<number> {
  try {
    return (await listAllMutations()).length;
  } catch {
    return 0; // no IndexedDB: nothing can be queued
  }
}

/**
 * Remove what this session left on the device: queued marks (they would be
 * replayed under the next user's sign-in) and the service worker's cached
 * coach reads (rosters, the whole-academy Today view).
 */
async function clearDeviceData(): Promise<void> {
  await Promise.allSettled([
    clearOfflineQueue(),
    typeof caches === "undefined"
      ? Promise.resolve(false)
      : caches.delete(COACH_SW_CACHE),
  ]);
}

export function PersonaLogoutButton({
  className = "",
  label = "Log out",
  labelClassName = "",
}: {
  className?: string;
  label?: string;
  labelClassName?: string;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);

  async function handleLogOut() {
    if (busy) return;
    const unsent = await unsentMarkCount();
    if (
      unsent > 0 &&
      !window.confirm(
        `${unsent} attendance ${unsent === 1 ? "mark hasn't" : "marks haven't"} been sent yet. ` +
          "Logging out deletes them from this device. Log out anyway?",
      )
    ) {
      return;
    }
    setBusy(true);
    try {
      await signOutCurrent();
      await clearDeviceData();
      // Drop every cached read before the next user can reach the shell.
      // Persona caches (and the localStorage-persisted coach cache) would
      // otherwise survive the session and be served to whoever logs in
      // next on a shared device.
      queryClient.clear();
      clearPersistedQueryCache();
      router.replace("/login");
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      aria-label={label}
      data-testid="persona-logout-button"
      disabled={busy}
      onClick={() => void handleLogOut()}
      className={`inline-flex items-center justify-center gap-2 transition-colors disabled:cursor-wait disabled:opacity-60 ${className}`}
    >
      <LogOut aria-hidden="true" size={18} strokeWidth={2} />
      <span className={labelClassName}>{label}</span>
    </button>
  );
}
