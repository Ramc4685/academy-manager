"use client";

import type { Route } from "next";
import { useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { ConfirmActionDialog } from "@/components/admin/confirm-action-dialog";

/**
 * Issue #893: one unsaved-changes guard for the whole admin shell.
 *
 * #863 added a guard, but it lived on the settings tab strip and only
 * intercepted the strip's own links — so a sidebar link, a drawer link, any
 * other in-app link, or a reload threw the draft away with no warning. The
 * guard now sits in the shell layout, which is mounted for every admin page,
 * and covers:
 *
 *  - in-app link navigation, via a document-level CAPTURE click listener.
 *    React attaches its own listeners at the root container (below
 *    `document`), so capturing here runs first and `next/link` skips its
 *    navigation once the event is default-prevented. Propagation is left
 *    alone on purpose, so a link's own handler still runs — the phone
 *    drawer's row closes the drawer, and the dialog opens over the page the
 *    reader is staying on. Intercepting links rather than patching the router
 *    is what keeps this additive: nothing in the nav has to know a guard
 *    exists.
 *  - full page unloads (reload, tab close, an external URL), via
 *    `beforeunload`. The browser's native prompt is the only option there —
 *    no dialog of ours can render during an unload.
 *
 * A same-document Back/Forward is NOT intercepted: cancelling a history pop
 * needs a sentinel entry pushed on every keystroke-driven dirty flip, and a
 * mis-timed one silently rewrites the reader's history. `beforeunload` still
 * covers the case where Back leaves the app entirely.
 *
 * `data-unsaved-guard-nav="replace"` on a link makes the guarded navigation a
 * `router.replace(..., { scroll: false })`, which is how the settings tab
 * strip switches panels without stacking a history entry per tab.
 */

interface UnsavedChangesValue {
  /** True when some mounted surface holds unsaved edits. */
  hasUnsaved: boolean;
  /** Publish (or clear) one surface's unsaved state. */
  setUnsaved: (key: string, unsaved: boolean) => void;
  /** Run `leave` now when nothing is unsaved, otherwise confirm first. */
  requestLeave: (leave: () => void) => void;
}

const UnsavedChangesContext = createContext<UnsavedChangesValue>({
  hasUnsaved: false,
  setUnsaved: () => {},
  // Outside the provider the guard is a pass-through, so a surface that
  // reports dirty state stays usable in isolation (and in unit tests).
  requestLeave: (leave) => leave(),
});

export function useUnsavedChanges(): UnsavedChangesValue {
  return useContext(UnsavedChangesContext);
}

/**
 * Publish this surface's unsaved-edit state for as long as it is mounted.
 * Clearing on unmount matters: the panel that holds the draft is the thing
 * the navigation unmounts.
 */
export function useReportUnsavedChanges(key: string, unsaved: boolean): void {
  const { setUnsaved } = useUnsavedChanges();
  // A layout effect, not a passive one: a controlled input's change commits
  // at the end of its own input event, and layout effects run inside that
  // commit, so the guard knows before any later click or keypress is
  // handled. A passive effect can be deferred past the next event; on the
  // nightly WebKit job that let a tab switch through with no dialog.
  useLayoutEffect(() => {
    setUnsaved(key, unsaved);
    return () => setUnsaved(key, false);
  }, [key, unsaved, setUnsaved]);
}

export function UnsavedChangesProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [keys, setKeys] = useState<ReadonlySet<string>>(() => new Set<string>());
  const [pending, setPending] = useState<(() => void) | null>(null);
  const hasUnsaved = keys.size > 0;

  // The leave checks read this, never `hasUnsaved`: state (and a ref synced
  // from it in an effect) only catches up a render after the surface reports,
  // so a tab switch or link click that followed a keystroke that closely
  // left without the dialog and dropped the edit. The ref is written in
  // `setUnsaved` itself, as the surface reports.
  const unsavedKeysRef = useRef<ReadonlySet<string>>(new Set<string>());

  const setUnsaved = useCallback((key: string, unsaved: boolean) => {
    const prev = unsavedKeysRef.current;
    if (prev.has(key) === unsaved) return;
    const next = new Set(prev);
    if (unsaved) next.add(key);
    else next.delete(key);
    unsavedKeysRef.current = next;
    setKeys(next);
  }, []);

  const requestLeave = useCallback((leave: () => void) => {
    if (unsavedKeysRef.current.size === 0) {
      leave();
      return;
    }
    // The setter takes an updater, so a function value has to be wrapped.
    setPending(() => leave);
  }, []);

  useEffect(() => {
    // Always attached, for the same reason as the ref above.
    function onClickCapture(event: MouseEvent) {
      if (unsavedKeysRef.current.size === 0) return;
      if (event.defaultPrevented || event.button !== 0) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const target = event.target;
      if (!(target instanceof Element)) return;
      const anchor = target.closest("a[href]");
      if (!(anchor instanceof HTMLAnchorElement)) return;
      if (anchor.hasAttribute("download")) return;
      if (anchor.target && anchor.target !== "_self") return;
      const url = new URL(anchor.href, window.location.href);
      // A cross-origin link is a full unload — `beforeunload` guards it.
      if (url.origin !== window.location.origin) return;
      const here = `${window.location.pathname}${window.location.search}`;
      const there = `${url.pathname}${url.search}`;
      if (there === here) return;
      const replace = anchor.getAttribute("data-unsaved-guard-nav") === "replace";
      event.preventDefault();
      setPending(() => () => {
        if (replace) router.replace(there as Route, { scroll: false });
        else router.push(there as Route);
      });
    }
    document.addEventListener("click", onClickCapture, true);
    return () => document.removeEventListener("click", onClickCapture, true);
  }, [router]);

  useEffect(() => {
    if (!hasUnsaved) return;
    function onBeforeUnload(event: BeforeUnloadEvent) {
      event.preventDefault();
      // Chrome still requires a non-undefined returnValue to prompt.
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [hasUnsaved]);

  const value = useMemo<UnsavedChangesValue>(
    () => ({ hasUnsaved, setUnsaved, requestLeave }),
    [hasUnsaved, setUnsaved, requestLeave],
  );

  return (
    <UnsavedChangesContext.Provider value={value}>
      {children}
      <ConfirmActionDialog
        open={pending !== null}
        onOpenChange={(open) => {
          if (!open) setPending(null);
        }}
        overline="Unsaved changes"
        title="Leave without saving?"
        consequence={
          <p data-testid="unsaved-changes-warning">
            This page has edits that have not been saved. Leaving now discards them.
          </p>
        }
        cancelLabel="Stay on this page"
        confirmLabel="Leave without saving"
        onConfirm={() => {
          const leave = pending;
          setPending(null);
          leave?.();
        }}
      />
    </UnsavedChangesContext.Provider>
  );
}
