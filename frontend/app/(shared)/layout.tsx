"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { onAuthChange } from "@/lib/auth/firebase";

// One surface for both the auth-pending skeleton and the resolved page, so the
// background never changes while `onAuthChange` settles (#451).
const shellClassName =
  "min-h-screen bg-rally-paper px-4 py-6 text-slate-950 dark:bg-rally-night dark:text-white";

export default function SharedLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [checked, setChecked] = useState(false);
  const [signedIn, setSignedIn] = useState(false);

  useEffect(
    () =>
      onAuthChange((user) => {
        setSignedIn(Boolean(user));
        setChecked(true);
        if (!user) router.replace("/login");
      }),
    [router]
  );

  // Auth unresolved, or signed out and mid-redirect to /login: hold the shell
  // with a neutral skeleton rather than flashing bare status text.
  if (!checked || !signedIn) {
    return (
      <div
        className={shellClassName}
        role="status"
        aria-busy="true"
        aria-label="Loading"
        data-testid="shared-auth-skeleton"
      >
        <div className="mx-auto w-full max-w-3xl space-y-4">
          <div className="h-8 w-48 animate-pulse rounded-xl shimmer" />
          <div className="h-28 animate-pulse rounded-2xl shimmer" />
          <div className="h-28 animate-pulse rounded-2xl shimmer" />
        </div>
      </div>
    );
  }

  return <main className={shellClassName}>{children}</main>;
}
