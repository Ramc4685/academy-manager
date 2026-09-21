"use client";

/**
 * The one "this did not load" box (issue #837).
 *
 * Every admin list used to fail differently — a red bar with no way out, a
 * grey line of prose, or nothing at all under a grid of zeros. This states the
 * failure once, as an alert, and offers the action the screen actually needs:
 * try the request again without a full page reload.
 */

import { Button } from "./button";

export function ErrorNotice({
  message,
  onRetry,
  retrying = false,
  testId,
  className,
}: {
  message: string;
  /** Wire to the query's `refetch`. Omit only when there is nothing to retry. */
  onRetry?: () => void;
  retrying?: boolean;
  testId?: string;
  className?: string;
}) {
  return (
    <div
      role="alert"
      data-testid={testId}
      className={`flex flex-wrap items-center justify-between gap-3 rounded-md border border-status-red-200 bg-status-red-50 px-4 py-3 text-sm text-status-red-800 ${
        className ?? ""
      }`}
    >
      <p className="min-w-0">{message}</p>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry} disabled={retrying}>
          {retrying ? "Trying…" : "Try again"}
        </Button>
      )}
    </div>
  );
}
