"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { onAuthChange } from "@/lib/auth/firebase";

/**
 * Post-login redirect stub.
 *
 * Wave 1A replaces this with a route that calls `/api/v2/me` to read role
 * claims and redirect to (coach) / (parent) / (admin). For Phase 0, anyone
 * signed in lands here and sees a placeholder.
 */
export default function PostLoginPage() {
  const router = useRouter();
  useEffect(() => onAuthChange((u) => { if (!u) router.replace("/login"); }), [router]);
  return (
    <main className="min-h-screen flex items-center justify-center px-4">
      <p className="text-center text-neutral-500">
        Signed in. (Role-aware routing lands in W1A-10.)
      </p>
    </main>
  );
}
