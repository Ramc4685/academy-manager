"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { getCurrentUser, homeForRoles, type CurrentUser, type UserRole } from "@/lib/api/me";
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

    return onAuthChange((firebaseUser) => {
      if (!firebaseUser) {
        if (!cancelled) {
          setState({ checked: true, authorized: false, user: null });
          router.replace("/login");
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
          router.replace(homeForRoles(currentUser.roles));
        })
        .catch(() => {
          if (!cancelled) {
            setState({ checked: true, authorized: false, user: null });
            router.replace("/login");
          }
        });
    });
  }, [requiredRole, router]);

  return state;
}
