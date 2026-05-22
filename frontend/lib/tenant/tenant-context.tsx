"use client";

/**
 * TenantContext.
 *
 * Surfaces the current user's academy memberships and the currently
 * selected one. Selection is persisted via `setActiveAcademyId` (which
 * stamps every v2 request with `X-Academy-Id`).
 *
 * The provider deliberately does NOT block render — when memberships
 * are still loading, consumers receive `status: "loading"` and the
 * shell renders a placeholder pill. Pages should not gate data fetches
 * on the active academy themselves; the v2 BFF resolves tenant from
 * the host + header.
 *
 * Per ADR-0007 the server is the source of truth for tenant resolution.
 * This provider is a UX convenience for multi-academy admins and never
 * grants tenant access on its own.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  listMyMemberships,
  type AcademyMembershipSummary,
} from "@/lib/api/v2/memberships";
import { getActiveAcademyId, setActiveAcademyId } from "@/lib/api/client";

interface TenantContextValueLoading {
  status: "loading";
  memberships: readonly AcademyMembershipSummary[];
  activeAcademyId: string | null;
  activeMembership: null;
  switchAcademy: (academyId: string) => void;
  refresh: () => void;
}

interface TenantContextValueReady {
  status: "ready" | "error";
  memberships: readonly AcademyMembershipSummary[];
  activeAcademyId: string | null;
  activeMembership: AcademyMembershipSummary | null;
  switchAcademy: (academyId: string) => void;
  refresh: () => void;
}

export type TenantContextValue = TenantContextValueLoading | TenantContextValueReady;

const TenantContext = createContext<TenantContextValue | null>(null);

export function TenantProvider({ children }: { children: ReactNode }) {
  const [memberships, setMemberships] = useState<AcademyMembershipSummary[]>([]);
  const [activeAcademyId, setActive] = useState<string | null>(
    typeof window === "undefined" ? null : getActiveAcademyId(),
  );
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    listMyMemberships()
      .then((res) => {
        if (cancelled) return;
        setMemberships(res.memberships);
        const persisted = getActiveAcademyId();
        const chosen =
          (persisted && res.memberships.find((m) => m.academy_id === persisted)?.academy_id) ||
          res.active_academy_id ||
          res.memberships[0]?.academy_id ||
          null;
        if (chosen) setActiveAcademyId(chosen);
        setActive(chosen);
        setStatus("ready");
      })
      .catch(() => {
        if (cancelled) return;
        setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [tick]);

  const switchAcademy = useCallback((academyId: string) => {
    setActiveAcademyId(academyId);
    setActive(academyId);
    // Force a soft refresh so React Query caches that depend on the
    // active academy refetch with the new header. Avoids a full reload
    // for the common single-membership case.
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("am:tenant-changed", { detail: academyId }));
    }
  }, []);

  const refresh = useCallback(() => setTick((n) => n + 1), []);

  const value = useMemo<TenantContextValue>(() => {
    const activeMembership =
      memberships.find((m) => m.academy_id === activeAcademyId) ?? null;
    if (status === "loading") {
      return {
        status: "loading",
        memberships,
        activeAcademyId,
        activeMembership: null,
        switchAcademy,
        refresh,
      };
    }
    return {
      status,
      memberships,
      activeAcademyId,
      activeMembership,
      switchAcademy,
      refresh,
    };
  }, [activeAcademyId, memberships, refresh, status, switchAcademy]);

  return <TenantContext.Provider value={value}>{children}</TenantContext.Provider>;
}

export function useTenant(): TenantContextValue {
  const ctx = useContext(TenantContext);
  if (!ctx) {
    // Safe fallback when consumed outside the provider (e.g. during
    // SSR or in a Storybook). Pages that truly need tenant should be
    // mounted under the admin layout.
    return {
      status: "loading",
      memberships: [],
      activeAcademyId: null,
      activeMembership: null,
      switchAcademy: () => undefined,
      refresh: () => undefined,
    } satisfies TenantContextValue;
  }
  return ctx;
}
