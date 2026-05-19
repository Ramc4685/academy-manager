"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { User } from "firebase/auth";

import { onAuthChange, signOutCurrent } from "@/lib/auth/firebase";

export default function CoachProfilePage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => onAuthChange(setUser), []);

  async function signOut() {
    await signOutCurrent();
    router.replace("/login");
  }

  return (
    <section data-testid="coach-profile">
      <header className="mb-4">
        <h1 className="text-2xl font-semibold">Profile</h1>
        <p className="text-sm text-neutral-500">Coach access</p>
      </header>

      <div className="rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900">
        <p className="text-sm text-neutral-500">Signed in as</p>
        <p className="mt-1 font-medium">{user?.email ?? "Coach"}</p>
      </div>

      <button
        onClick={() => void signOut()}
        className="mt-4 min-h-touch rounded-md border border-neutral-300 px-4 text-sm font-medium text-neutral-800 hover:bg-neutral-50 dark:border-neutral-700 dark:text-neutral-100 dark:hover:bg-neutral-900"
      >
        Sign out
      </button>
    </section>
  );
}
