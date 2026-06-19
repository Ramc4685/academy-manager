"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { LogOut } from "lucide-react";

import { signOutCurrent } from "@/lib/auth/firebase";

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
  const [busy, setBusy] = useState(false);

  async function handleLogOut() {
    if (busy) return;
    setBusy(true);
    try {
      await signOutCurrent();
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
