"use client";

// One surface for every pending state under `app/(shared)`, so the background
// never changes while `onAuthChange` — or the per-page role lookup that follows
// it — settles (#451).
export const sharedShellClassName =
  "min-h-screen bg-rally-paper px-4 py-6 text-slate-950 dark:bg-rally-night dark:text-white";

export function SharedShellSkeleton({
  testId,
  className,
}: {
  testId: string;
  /** Omit inside the (shared) layout `<main>`, which already paints the surface. */
  className?: string;
}) {
  return (
    <div
      className={className}
      role="status"
      aria-busy="true"
      aria-label="Loading"
      data-testid={testId}
    >
      <div className="mx-auto w-full max-w-3xl space-y-4">
        <div className="h-8 w-48 animate-pulse rounded-xl shimmer" />
        <div className="h-28 animate-pulse rounded-2xl shimmer" />
        <div className="h-28 animate-pulse rounded-2xl shimmer" />
      </div>
    </div>
  );
}
