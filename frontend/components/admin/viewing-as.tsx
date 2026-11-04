"use client";

import { useCallback, useEffect, useState } from "react";

import { useIsOwner } from "@/components/admin/owner-context";
import { VIEWING_AS_OPTIONS, isViewingAs, type ViewingAs } from "@/lib/family-money-view";

/**
 * The owner's "Viewing as" preview (L2b, #553): see the family pages as
 * billing or front desk would, money-wise. It only narrows what the owner's
 * own payload shows; the real redaction for billing and front-desk staff is
 * the server's. Per tab (sessionStorage), so a preview never sticks around
 * as a surprise on the next visit.
 */
const STORAGE_KEY = "am:viewing-as";
const CHANGE_EVENT = "am:viewing-as-changed";

function readStored(): ViewingAs {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    return isViewingAs(raw) ? raw : "self";
  } catch {
    return "self";
  }
}

function writeStored(value: ViewingAs): void {
  try {
    if (value === "self") window.sessionStorage.removeItem(STORAGE_KEY);
    else window.sessionStorage.setItem(STORAGE_KEY, value);
  } catch {
    // Storage unavailable: the preview still works for this render tree.
  }
}

/** The current preview; always `self` for anyone who is not the owner. */
export function useViewingAs(): [ViewingAs, (next: ViewingAs) => void] {
  const isOwner = useIsOwner();
  const [value, setValue] = useState<ViewingAs>("self");
  useEffect(() => {
    setValue(readStored());
    const onChange = () => setValue(readStored());
    window.addEventListener(CHANGE_EVENT, onChange);
    return () => window.removeEventListener(CHANGE_EVENT, onChange);
  }, []);
  const set = useCallback((next: ViewingAs) => {
    writeStored(next);
    setValue(next);
    window.dispatchEvent(new Event(CHANGE_EVENT));
  }, []);
  return [isOwner ? value : "self", set];
}

/** Owner-only select. Renders nothing for anyone else. */
export function ViewingAsToggle() {
  const isOwner = useIsOwner();
  const [viewingAs, setViewingAs] = useViewingAs();
  if (!isOwner) return null;
  return (
    <ViewingAsControl value={viewingAs} onChange={setViewingAs} />
  );
}

/** The presentational control, exported for tests. */
export function ViewingAsControl({
  value,
  onChange,
}: {
  value: ViewingAs;
  onChange: (next: ViewingAs) => void;
}) {
  const label = VIEWING_AS_OPTIONS.find((o) => o.id === value)?.label ?? "Owner (you)";
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm" data-testid="viewing-as">
      <label className="flex items-center gap-2 text-rally-muted">
        <span>Viewing as</span>
        <select
          data-testid="viewing-as-select"
          value={value}
          onChange={(e) => {
            const next = e.target.value;
            if (isViewingAs(next)) onChange(next);
          }}
          className="min-h-9 rounded-md border border-rally-line bg-white px-2 py-1 text-sm text-rally-ink focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600 dark:bg-neutral-900"
        >
          {VIEWING_AS_OPTIONS.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      {value !== "self" ? (
        <span
          role="status"
          data-testid="viewing-as-note"
          className="rounded-full bg-rally-cobalt-50 px-2 py-0.5 text-xs text-status-blue-800"
        >
          Preview: money shown as {label} sees it
        </span>
      ) : null}
    </div>
  );
}
