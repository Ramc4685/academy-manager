"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { onAuthChange } from "@/lib/auth/firebase";

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

  if (!checked) {
    return <div className="min-h-screen flex items-center justify-center text-neutral-500">Loading...</div>;
  }

  if (!signedIn) {
    return <div className="min-h-screen flex items-center justify-center text-neutral-500">Redirecting...</div>;
  }

  return (
    <main className="min-h-screen bg-slate-50 px-4 py-6 text-slate-950 dark:bg-slate-950 dark:text-white">
      {children}
    </main>
  );
}
