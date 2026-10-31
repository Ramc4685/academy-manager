"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { SharedShellSkeleton } from "@/components/shared/shell-skeleton";
import { getCurrentUser } from "@/lib/api/me";

export default function CalendarPage() {
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;
    getCurrentUser()
      .then((data) => {
        if (cancelled) return;
        const roles = data.roles;
        const href = roles.includes("admin")
          ? "/admin/sessions"
          : roles.includes("coach")
            ? "/coach/calendar"
            : roles.includes("parent")
              ? "/parent/calendar"
              : "/login";
        router.replace(href);
      })
      .catch(() => {
        if (!cancelled) router.replace("/login");
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  // The role lookup runs after the layout has already painted the shell, so keep
  // the same skeleton instead of flashing bare status text here (#451).
  return <SharedShellSkeleton testId="shared-role-redirect-skeleton" />;
}
