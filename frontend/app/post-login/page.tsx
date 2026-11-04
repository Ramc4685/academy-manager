"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { onAuthChange } from "@/lib/auth/firebase";
import { clearBffIdentityCookie } from "@/lib/api/auth-bridge-cookie";
import {
  getCurrentUserWithToken,
  hasPlatformAccess,
  homeForRoles,
} from "@/lib/api/me";
import {
  clearPersonaHintCookie,
  setPersonaHintCookie,
} from "@/lib/auth/persona-hint-cookie";
import { loginPathForError } from "@/lib/auth/login-error";
import { sanitizeReturnPath } from "@/lib/auth/persona-route-guard";
import { isAuthRejection, withTransientRetry } from "@/lib/auth/me-failure";

export default function PostLoginPage() {
  const router = useRouter();
  const [attempt, setAttempt] = useState(0);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(
    () =>
      onAuthChange((user) => {
        if (!user) {
          clearBffIdentityCookie();
          clearPersonaHintCookie();
          router.replace("/login");
          return;
        }

        setUnavailable(false);
        void withTransientRetry(() =>
          user.getIdToken(true).then((idToken) => getCurrentUserWithToken(idToken)),
        )
          .then((currentUser) => {
            // Persona hint for the edge gate (#451): written here, where the
            // persona is first known, so the next visit to a shell is
            // decided before anything paints.
            setPersonaHintCookie(
              currentUser.roles,
              hasPlatformAccess(currentUser),
            );
            // The edge gate stashed the deep link the visitor actually asked
            // for on /login?returnTo=... and the login page handed it on
            // (#451); honour it when it is a safe in-app path, otherwise fall
            // back to this persona's home.
            const returnTo = sanitizeReturnPath(readReturnToParam());
            replaceLocation(router, returnTo ?? homeForRoles(currentUser.roles));
          })
          .catch((err: unknown) => {
            if (isAuthRejection(err)) {
              // 401/403: the backend rejected this session — treat as a real
              // auth failure and bounce to /login with the reason code.
              clearBffIdentityCookie();
              clearPersonaHintCookie();
              replaceLocation(router, loginPathForError(err));
              return;
            }
            // Transient outage (5xx / network / timeout): the Firebase
            // session is still valid, so keep the identity cookie and let
            // the user retry instead of silently logging them out (#515).
            setUnavailable(true);
          });
      }),
    [router, attempt]
  );

  if (unavailable) {
    return (
      <main className="min-h-screen flex items-center justify-center px-4">
        <div className="flex max-w-sm flex-col items-center gap-3 text-center">
          <p className="text-base font-semibold text-neutral-800">
            We can&apos;t reach the server right now
          </p>
          <p className="text-sm text-neutral-500">
            You&apos;re still signed in — this is usually a brief connection
            hiccup. Check your connection and try again.
          </p>
          <button
            type="button"
            data-testid="auth-unavailable-retry"
            onClick={() => setAttempt((n) => n + 1)}
            className="min-h-touch mt-1 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700"
          >
            Retry
          </button>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen flex items-center justify-center px-4">
      <p className="text-center text-neutral-500">Signing you in...</p>
    </main>
  );
}

/**
 * Read `?returnTo=` straight off the URL rather than via `useSearchParams`,
 * which would force this page behind a Suspense boundary. The effect only runs
 * in the browser, so `window` is always there.
 */
function readReturnToParam(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get("returnTo");
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
