"use client";

/**
 * Shell back button.
 *
 * The installed PWA has no browser chrome and the iOS edge swipe is
 * unreliable in standalone mode, so every non-top-level page gets a chevron
 * in the shell header. Renders nothing on the shell's known top-level routes.
 *
 * Click: `window.history.length > 1` → `router.back()`; otherwise (a deep-
 * linked launch has history length 1) push the nearest known parent route.
 */

import type { Route } from "next";
import { usePathname, useRouter } from "next/navigation";

import { isTopLevel, parentRoute } from "./parent-route";

export function ShellBackButton({
  known,
  home,
  variant = "light",
}: {
  known: readonly string[];
  home: string;
  variant?: "light" | "dark";
}) {
  const pathname = usePathname();
  const router = useRouter();

  if (!pathname || isTopLevel(pathname, known)) return null;

  const colour =
    variant === "dark"
      ? "text-slate-300 hover:bg-white/10"
      : "text-rally-muted hover:bg-neutral-100";

  const onClick = () => {
    if (typeof window !== "undefined" && window.history.length > 1) {
      router.back();
      return;
    }
    router.push(parentRoute(pathname, known, home) as Route);
  };

  return (
    <button
      type="button"
      aria-label="Back"
      data-testid="shell-back-button"
      onClick={onClick}
      className={`min-h-touch min-w-touch flex shrink-0 items-center justify-center rounded-md ${colour}`}
    >
      <svg
        width="20"
        height="20"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <polyline points="15 18 9 12 15 6" />
      </svg>
    </button>
  );
}
