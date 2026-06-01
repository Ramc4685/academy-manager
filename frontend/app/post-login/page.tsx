"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { onAuthChange } from "@/lib/auth/firebase";
import { getCurrentUserWithToken, homeForRoles } from "@/lib/api/me";

export default function PostLoginPage() {
  const router = useRouter();

  useEffect(
    () =>
      onAuthChange((user) => {
        if (!user) {
          router.replace("/login");
          return;
        }

        void user
          .getIdToken()
          .then((idToken) => getCurrentUserWithToken(idToken))
          .then((currentUser) => {
            router.replace(homeForRoles(currentUser.roles));
          })
          .catch(() => {
            router.replace("/login");
          });
      }),
    [router]
  );

  return (
    <main className="min-h-screen flex items-center justify-center px-4">
      <p className="text-center text-neutral-500">Signing you in...</p>
    </main>
  );
}
