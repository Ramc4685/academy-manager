"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import {
  getCurrentUser,
  homeForRoles,
  type CurrentUser,
  type UserRole,
} from "@/lib/api/me";
import { onAuthChange } from "@/lib/auth/firebase";

export type PersonaAuthState =
  | { checked: false; authorized: false; user: null }
  | { checked: true; authorized: false; user: null }
  | { checked: true; authorized: true; user: CurrentUser };

export function usePersonaAuth(requiredRole: UserRole): PersonaAuthState {
  const router = useRouter();
  const [state, setState] = useState<PersonaAuthState>({
    checked: false,
    authorized: false,
    user: null,
  });

  useEffect(() => {
    let cancelled = false;

    const unsubscribe = onAuthChange((firebaseUser) => {
      if (!firebaseUser) {
        if (!cancelled) {
          setState({ checked: true, authorized: false, user: null });
          replaceLocation(router, "/login");
        }
        return;
      }

      void getCurrentUser()
        .then((currentUser) => {
          if (cancelled) return;
          if (currentUser.roles.includes(requiredRole)) {
            setState({ checked: true, authorized: true, user: currentUser });
            return;
          }
          setState({ checked: true, authorized: false, user: null });
          const target = new URL(
            homeForRoles(currentUser.roles),
            window.location.origin,
          );
          target.searchParams.set("access_denied", requiredRole);
          replaceLocation(router, `${target.pathname}${target.search}`);
        })
        .catch(() => {
          if (!cancelled) {
            setState({ checked: true, authorized: false, user: null });
            replaceLocation(router, "/login");
          }
        });
    });
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, [requiredRole, router]);

  return state;
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
  }, 1_000);
}
