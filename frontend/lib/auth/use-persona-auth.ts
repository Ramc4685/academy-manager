"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import {
  getCurrentUser,
  hasPlatformAccess,
  homeForRoles,
  isPlatformAdmin,
  type CurrentUser,
  type UserRole,
} from "@/lib/api/me";
import { onAuthChange } from "@/lib/auth/firebase";
import { loginPathForError } from "@/lib/auth/login-error";

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
        .catch((err: unknown) => {
          if (!cancelled) {
            setState({ checked: true, authorized: false, user: null });
            replaceLocation(router, loginPathForError(err));
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

export type PlatformAuthState =
  | { checked: false; authorized: false; user: null; isAdmin: false }
  | { checked: true; authorized: false; user: null; isAdmin: false }
  | { checked: true; authorized: true; user: CurrentUser; isAdmin: boolean };

/**
 * Guard for the `(platform)` surface.
 *
 * Platform capability lives in `platform_roles`, never in the tenant-scoped
 * `roles`, so this cannot reuse `usePersonaAuth`. `isAdmin` distinguishes
 * `platform_admin` (may mutate) from `platform_support` (read-only) so the UI
 * can hide mutation controls — the server independently 404s support writes.
 */
export function usePlatformAuth(): PlatformAuthState {
  const router = useRouter();
  const [state, setState] = useState<PlatformAuthState>({
    checked: false,
    authorized: false,
    user: null,
    isAdmin: false,
  });

  useEffect(() => {
    let cancelled = false;

    const unsubscribe = onAuthChange((firebaseUser) => {
      if (!firebaseUser) {
        if (!cancelled) {
          setState({ checked: true, authorized: false, user: null, isAdmin: false });
          replaceLocation(router, "/login");
        }
        return;
      }

      void getCurrentUser()
        .then((currentUser) => {
          if (cancelled) return;
          if (hasPlatformAccess(currentUser)) {
            setState({
              checked: true,
              authorized: true,
              user: currentUser,
              isAdmin: isPlatformAdmin(currentUser),
            });
            return;
          }
          setState({ checked: true, authorized: false, user: null, isAdmin: false });
          const target = new URL(
            homeForRoles(currentUser.roles),
            window.location.origin,
          );
          target.searchParams.set("access_denied", "platform");
          replaceLocation(router, `${target.pathname}${target.search}`);
        })
        .catch(() => {
          if (!cancelled) {
            setState({ checked: true, authorized: false, user: null, isAdmin: false });
            replaceLocation(router, "/login");
          }
        });
    });
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, [router]);

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
