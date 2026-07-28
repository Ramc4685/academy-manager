"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { getCurrentUser } from "@/lib/api/me";

export default function MessagesPage() {
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;
    getCurrentUser()
      .then((data) => {
        if (cancelled) return;
        const roles = data.roles;
        const href = roles.includes("admin")
          ? "/admin/messages"
          : roles.includes("coach")
            ? "/coach/messages"
            : roles.includes("parent")
              ? "/parent/messages"
              : "/post-login";
        router.replace(href);
      })
      .catch(() => {
        if (!cancelled) router.replace("/login");
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  return (
    <div className="min-h-screen flex items-center justify-center text-neutral-500">
      Redirecting...
    </div>
  );
}
