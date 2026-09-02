"use client";

import { useCallback, useEffect, useState } from "react";
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
import { isAuthRejection, withTransientRetry } from "@/lib/auth/me-failure";

export type PersonaAuthState =
  | { checked: false; authorized: false; user: null; unavailable?: false }
  | { checked: true; authorized: false; user: null; unavailable?: false }
  /**
   * The /me check failed for a non-auth reason (backend 5xx, network blip,
   * client-side abort) even after retries. The Firebase session is still
   * valid, so the shell must NOT bounce to /login — it shows a "can't reach
   * the server" state and offers `retry` instead (issue #515).
   */
  | { checked: true; authorized: false; user: null; unavailable: true }
  | { checked: true; authorized: true; user: CurrentUser; unavailable?: false };

export interface PersonaAuthOptions {
  /**
   * Roles that may enter this shell besides `requiredRole`. Used by the coach
   * shell so academy admins/owners can cover any session (#632). The
   * access-denied redirect still names `requiredRole`.
   */
  alsoAllow?: readonly UserRole[];
}

export function usePersonaAuth(
  requiredRole: UserRole,
  options: PersonaAuthOptions = {},
): PersonaAuthState & {
  retry: () => void;
} {
  const router = useRouter();
  const allowedRoles = [requiredRole, ...(options.alsoAllow ?? [])];
  // Stable dependency for the effect below; the caller passes a literal.
  const allowedKey = allowedRoles.join(",");
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<PersonaAuthState>({
    checked: false,
    authorized: false,
    user: null,
  });

  const retry = useCallback(() => {
    setState({ checked: false, authorized: false, user: null });
    setAttempt((n) => n + 1);
  }, []);

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

      void withTransientRetry(getCurrentUser)
        .then((currentUser) => {
          if (cancelled) return;
          if (allowedKey.split(",").some((role) => currentUser.roles.includes(role as UserRole))) {
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
          if (cancelled) return;
          if (isAuthRejection(err)) {
            // 401/403: the session really is dead — bounce to /login with
            // the backend's reason code.
            setState({ checked: true, authorized: false, user: null });
            replaceLocation(router, loginPathForError(err));
            return;
          }
          // Transient outage: keep the user where they are and let the
          // shell offer a retry instead of logging them out.
          setState({
            checked: true,
            authorized: false,
            user: null,
            unavailable: true,
          });
        });
    });
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, [requiredRole, allowedKey, router, attempt]);

  return { ...state, retry };
}

export type PlatformAuthState =
  | {
      checked: false;
      authorized: false;
      user: null;
      isAdmin: false;
      unavailable?: false;
    }
  | {
      checked: true;
      authorized: false;
      user: null;
      isAdmin: false;
      unavailable?: false;
    }
  /** Same transient-outage state as `PersonaAuthState` (issue #515). */
  | {
      checked: true;
      authorized: false;
      user: null;
      isAdmin: false;
      unavailable: true;
    }
  | {
      checked: true;
      authorized: true;
      user: CurrentUser;
      isAdmin: boolean;
      unavailable?: false;
    };

/**
 * Guard for the `(platform)` surface.
 *
 * Platform capability lives in `platform_roles`, never in the tenant-scoped
 * `roles`, so this cannot reuse `usePersonaAuth`. `isAdmin` distinguishes
 * `platform_admin` (may mutate) from `platform_support` (read-only) so the UI
 * can hide mutation controls — the server independently 404s support writes.
 */
export function usePlatformAuth(): PlatformAuthState & { retry: () => void } {
  const router = useRouter();
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<PlatformAuthState>({
    checked: false,
    authorized: false,
    user: null,
    isAdmin: false,
  });

  const retry = useCallback(() => {
    setState({ checked: false, authorized: false, user: null, isAdmin: false });
    setAttempt((n) => n + 1);
  }, []);

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

      void withTransientRetry(getCurrentUser)
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
        .catch((err: unknown) => {
          if (cancelled) return;
          if (isAuthRejection(err)) {
            setState({
              checked: true,
              authorized: false,
              user: null,
              isAdmin: false,
            });
            replaceLocation(router, loginPathForError(err));
            return;
          }
          setState({
            checked: true,
            authorized: false,
            user: null,
            isAdmin: false,
            unavailable: true,
          });
        });
    });
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, [router, attempt]);

  return { ...state, retry };
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
