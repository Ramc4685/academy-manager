"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";

const ROLE_LABELS: Record<string, string> = {
  admin: "admin",
  coach: "coach",
  parent: "parent",
};

export function AccessDeniedNotice() {
  const pathname = usePathname();
  const [deniedRole, setDeniedRole] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const role = params.get("access_denied");
    setDeniedRole(role ? ROLE_LABELS[role] ?? role : null);
  }, [pathname]);

  if (!deniedRole) return null;

  return (
    <div
      role="alert"
      data-testid="persona-access-denied"
      className="mb-4 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100"
    >
      You do not have {deniedRole} access. You have been redirected to your available workspace.
    </div>
  );
}
