"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { registerMutationErrorSink } from "@/lib/query/mutation-errors";

export type ToastKind = "success" | "error" | "info";

export interface ToastOptions {
  kind?: ToastKind;
  title: string;
  description?: string;
  durationMs?: number;
}

interface ToastItem extends ToastOptions {
  id: string;
  kind: ToastKind;
}

interface ToastContextValue {
  toast: (opts: ToastOptions) => string;
  dismiss: (id: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const MAX_STACK = 3;
const DEFAULT_DURATION_MS = 5000;

const KIND_CLASSES: Record<ToastKind, string> = {
  success: "border-status-green-500 bg-status-green-50 text-status-green-800",
  error: "border-status-red-500 bg-status-red-50 text-status-red-800",
  info: "border-rally-cobalt-500 bg-rally-cobalt-50 text-status-blue-800",
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  const counter = useRef(0);

  const dismiss = useCallback((id: string) => {
    setItems((prev) => prev.filter((t) => t.id !== id));
    const timer = timers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
  }, []);

  const toast = useCallback(
    (opts: ToastOptions) => {
      const id = `toast-${counter.current++}`;
      const kind = opts.kind ?? "info";
      const item: ToastItem = { ...opts, id, kind };
      // Cap the visible stack at MAX_STACK, dropping the oldest.
      setItems((prev) => [...prev.slice(-(MAX_STACK - 1)), item]);
      // Error toasts stick unless the caller sets an explicit duration.
      const sticky = kind === "error" && opts.durationMs === undefined;
      if (!sticky) {
        const timer = setTimeout(() => dismiss(id), opts.durationMs ?? DEFAULT_DURATION_MS);
        timers.current.set(id, timer);
      }
      return id;
    },
    [dismiss],
  );

  const value = useMemo(() => ({ toast, dismiss }), [toast, dismiss]);

  // Surface globally-unhandled mutation failures (#509) as error toasts.
  useEffect(
    () =>
      registerMutationErrorSink(({ title, description }) => {
        toast({ kind: "error", title, description });
      }),
    [toast],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-[max(1rem,env(safe-area-inset-bottom,0px))] z-[60] flex flex-col items-center gap-2 px-4 sm:inset-x-auto sm:right-4 sm:items-end">
        {items.map((t) => (
          <div
            key={t.id}
            role={t.kind === "error" ? "alert" : "status"}
            className={`pointer-events-auto w-full max-w-sm rounded-lg border px-4 py-3 shadow-lg ${KIND_CLASSES[t.kind]}`}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm font-semibold">{t.title}</p>
                {t.description && <p className="mt-0.5 text-xs">{t.description}</p>}
              </div>
              <button
                type="button"
                onClick={() => dismiss(t.id)}
                aria-label="Dismiss notification"
                className="shrink-0 opacity-70 transition-opacity hover:opacity-100"
              >
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  aria-hidden="true"
                >
                  <path d="M6 6l12 12M18 6L6 18" />
                </svg>
              </button>
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within a ToastProvider");
  return ctx;
}
