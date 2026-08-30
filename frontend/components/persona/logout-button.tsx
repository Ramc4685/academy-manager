"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { LogOut } from "lucide-react";

import { signOutCurrent } from "@/lib/auth/firebase";
import { clearPersistedQueryCache } from "@/lib/query/persistence";

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
    setBusy(true);
    try {
      await signOutCurrent();
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
