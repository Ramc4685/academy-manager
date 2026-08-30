/**
 * Global mutation error feedback (#509).
 *
 * The app has ~28 `useMutation` sites that never render `error`/`isError` and
 * define no `onError`, so backend failures (409/500, or the 20s client abort)
 * were swallowed and the UI silently reverted to idle.
 *
 * `createAppMutationCache()` installs a `MutationCache` `onError` default that
 * pushes every otherwise-unhandled mutation failure to the mounted
 * `ToastProvider` (via the sink registry below). Mutations that declare their
 * own `onError` — i.e. already show contextual feedback — are skipped, as are
 * mutations that opt out with `meta: { suppressGlobalError: true }`.
 *
 * The sink indirection exists because the QueryClient is created above the
 * persona layouts, while the `ds/toast` ToastProvider (a React context) is
 * mounted inside them. The ToastProvider registers itself on mount.
 */

export interface MutationErrorNotice {
  title: string;
  description?: string;
}

type MutationErrorSink = (notice: MutationErrorNotice) => void;

let activeSink: MutationErrorSink | null = null;

/** Register the toast sink. Returns an unregister function for unmount. */
export function registerMutationErrorSink(sink: MutationErrorSink): () => void {
  activeSink = sink;
  return () => {
    if (activeSink === sink) activeSink = null;
  };
}

function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    ((error as { name?: unknown }).name === "AbortError" ||
      (error as { name?: unknown }).name === "TimeoutError")
  );
}

function apiStatus(error: unknown): number | null {
  if (
    typeof error === "object" &&
    error !== null &&
    "status" in error &&
    typeof (error as { status: unknown }).status === "number"
  ) {
    return (error as { status: number }).status;
  }
  return null;
}

/** Human-readable title/description for an arbitrary mutation failure. */
export function describeMutationError(error: unknown): MutationErrorNotice {
  if (isAbortError(error)) {
    return {
      title: "Request timed out",
      description: "The server took too long to respond. Please try again.",
    };
  }
  const status = apiStatus(error);
  const message =
    error instanceof Error && error.message && error.message !== "Request failed"
      ? error.message
      : undefined;
  if (status !== null && status >= 500) {
    return {
      title: "Something went wrong",
      description: message ?? "The server hit an unexpected error. Please try again.",
    };
  }
  return {
    title: "Action failed",
    description: message ?? "The request could not be completed. Please try again.",
  };
}

/**
 * Shape-only view of the mutation passed to `MutationCache.onError`.
 * Kept structural so this module stays testable without the cache internals.
 */
interface MutationLike {
  options: { onError?: unknown };
  meta?: Record<string, unknown>;
}

/** Decide whether the global handler should surface this failure. */
export function shouldNotifyGlobally(mutation: MutationLike): boolean {
  if (typeof mutation.options.onError === "function") return false;
  if (mutation.meta?.suppressGlobalError === true) return false;
  return true;
}

/** The global onError default. Exported for `createAppMutationCache` and tests. */
export function handleGlobalMutationError(error: unknown, mutation: MutationLike): void {
  if (!shouldNotifyGlobally(mutation)) return;
  const notice = describeMutationError(error);
  if (activeSink) {
    activeSink(notice);
  } else {
    // No ToastProvider mounted (e.g. auth pages) — at least keep it observable.
    console.error("[mutation]", notice.title, notice.description ?? "", error);
  }
}
