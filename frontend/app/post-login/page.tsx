"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { onAuthChange } from "@/lib/auth/firebase";
import { clearBffIdentityCookie } from "@/lib/api/auth-bridge-cookie";
import { getCurrentUserWithToken, homeForRoles } from "@/lib/api/me";
import { loginPathForError } from "@/lib/auth/login-error";

export default function PostLoginPage() {
  const router = useRouter();

  useEffect(
    () =>
      onAuthChange((user) => {
        if (!user) {
          clearBffIdentityCookie();
          router.replace("/login");
          return;
        }

        void user
          .getIdToken(true)
          .then((idToken) => getCurrentUserWithToken(idToken))
          .then((currentUser) => {
            replaceLocation(router, homeForRoles(currentUser.roles));
          })
          .catch((err: unknown) => {
            clearBffIdentityCookie();
            replaceLocation(router, loginPathForError(err));
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

function replaceLocation(
  router: ReturnType<typeof useRouter>,
  path: string,
): void {
  router.replace(path as Parameters<typeof router.replace>[0]);
  window.setTimeout(() => {
    const current = `${window.location.pathname}${window.location.search}`;
    if (current !== path) {
      window.location.replace(path);
    }
  }, 500);
}
