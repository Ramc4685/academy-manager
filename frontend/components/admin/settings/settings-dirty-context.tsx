"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

/**
 * Tracks which settings panels hold unsaved edits (#863).
 *
 * Only ONE panel is mounted at a time (the settings page renders the panel
 * matching `?panel=`), so switching tabs used to unmount the panel and throw
 * its draft away with no warning. Each panel already derives a `dirty` flag
 * for its own Save button; this context lifts that flag to the tab strip so
 * the strip can confirm before it navigates.
 *
 * Keyed by panel id rather than a single boolean because Self-service renders
 * two independent cards (self-service + departure policy) — a shared boolean
 * would let the clean card clear the dirty one's flag.
 */
interface SettingsDirtyValue {
  /** True when any mounted panel holds unsaved edits. */
  dirty: boolean;
  setPanelDirty: (panel: string, dirty: boolean) => void;
}

const SettingsDirtyContext = createContext<SettingsDirtyValue>({
  dirty: false,
  setPanelDirty: () => {},
});

export function SettingsDirtyProvider({ children }: { children: ReactNode }) {
  const [dirtyPanels, setDirtyPanels] = useState<ReadonlySet<string>>(() => new Set<string>());

  const setPanelDirty = useCallback((panel: string, dirty: boolean) => {
    setDirtyPanels((prev) => {
      if (prev.has(panel) === dirty) return prev;
      const next = new Set(prev);
      if (dirty) next.add(panel);
      else next.delete(panel);
      return next;
    });
  }, []);

  const value = useMemo<SettingsDirtyValue>(
    () => ({ dirty: dirtyPanels.size > 0, setPanelDirty }),
    [dirtyPanels, setPanelDirty]
  );

  return <SettingsDirtyContext.Provider value={value}>{children}</SettingsDirtyContext.Provider>;
}

export function useSettingsDirty(): SettingsDirtyValue {
  return useContext(SettingsDirtyContext);
}

/**
 * Publish a panel's unsaved-edit state. Safe outside the provider (the default
 * context is a no-op), so panels stay usable in isolation.
 *
 * `dirty` is derived from form-vs-loaded comparison in every panel, so a
 * successful save clears it on its own once the invalidated query refetches —
 * nothing has to reset it by hand.
 */
export function useReportSettingsDirty(panel: string, dirty: boolean): void {
  const { setPanelDirty } = useSettingsDirty();
  useEffect(() => {
    setPanelDirty(panel, dirty);
    return () => setPanelDirty(panel, false);
  }, [panel, dirty, setPanelDirty]);
}
