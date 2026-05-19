"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";

interface ActionSlotContextValue {
  /** The currently registered topbar action node, if any. */
  action: ReactNode | null;
  /** Replace the topbar action. Pass `null` to clear. */
  setAction: (node: ReactNode | null) => void;
}

const ActionSlotContext = createContext<ActionSlotContextValue | null>(null);

export function AdminActionSlotProvider({ children }: { children: ReactNode }) {
  const [action, setActionState] = useState<ReactNode | null>(null);
  const setAction = useCallback((node: ReactNode | null) => {
    setActionState(node);
  }, []);
  const value = useMemo(() => ({ action, setAction }), [action, setAction]);
  return <ActionSlotContext.Provider value={value}>{children}</ActionSlotContext.Provider>;
}

/** Render the currently-registered topbar action, or null. */
export function AdminActionSlotOutlet() {
  const ctx = useContext(ActionSlotContext);
  return ctx?.action ?? null;
}

/**
 * Register a topbar action from inside a page. The action is cleared
 * automatically on unmount, so each page only sees its own action.
 */
export function useAdminAction(node: ReactNode | null) {
  const ctx = useContext(ActionSlotContext);
  useEffect(() => {
    if (!ctx) return;
    ctx.setAction(node);
    return () => ctx.setAction(null);
  }, [ctx, node]);
}
