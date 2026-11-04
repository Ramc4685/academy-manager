"use client";

/**
 * Settings panels used to flash "Saved." and clear it after 2s, so an admin
 * who looked away could not tell a save from a no-op (#863). The panels now
 * keep the timestamp until the panel unmounts.
 */
export function savedAtNow(): string {
  return new Date().toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
}

export function SavedNote({ at }: { at: string | null }) {
  if (!at) return null;
  return <p className="text-sm font-medium text-emerald-700">Saved at {at}</p>;
}
