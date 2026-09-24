"use client";

/**
 * UI-7 (critique run 4, leftover 7): a horizontally scrolling chip or tab
 * strip on a phone showed three of ten chips with nothing to say the rest
 * existed. `useOverflowEdges` reports which edges still have content past
 * them; `OverflowCue` paints a fade and a chevron on that edge.
 *
 * Decorative only (`aria-hidden`, no pointer events): the strip itself stays
 * the keyboard and screen-reader surface, and every chip is still reachable
 * by Tab or swipe.
 */

import { ChevronLeft, ChevronRight } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

export interface OverflowEdges {
  left: boolean;
  right: boolean;
}

/** Pure edge maths, exported for unit tests. 1px slack absorbs sub-pixel widths. */
export function overflowEdges(el: {
  scrollLeft: number;
  clientWidth: number;
  scrollWidth: number;
}): OverflowEdges {
  return {
    left: el.scrollLeft > 1,
    right: el.scrollLeft + el.clientWidth < el.scrollWidth - 1,
  };
}

type ObserverCtors = {
  ResizeObserver?: typeof ResizeObserver;
  MutationObserver?: typeof MutationObserver;
};

/**
 * Calls `onChange` whenever the strip's scrollable width may have changed:
 * the strip itself resizes, ANY direct child resizes (a chip's live count
 * badge filling in), or chips are added or removed anywhere in the strip.
 * Observing only the strip and its first child missed a later chip growing,
 * which changes scrollWidth without changing the strip's own box.
 *
 * Exported (with injectable observer constructors) for unit tests.
 */
export function watchStripContent(
  el: Element,
  onChange: () => void,
  ctors: ObserverCtors = {
    ResizeObserver: typeof ResizeObserver === "undefined" ? undefined : ResizeObserver,
    MutationObserver: typeof MutationObserver === "undefined" ? undefined : MutationObserver,
  },
): () => void {
  const resize = ctors.ResizeObserver ? new ctors.ResizeObserver(() => onChange()) : null;
  const observeAll = () => {
    if (!resize) return;
    resize.disconnect();
    resize.observe(el);
    for (const child of Array.from(el.children)) resize.observe(child);
  };
  observeAll();
  const mutation = ctors.MutationObserver
    ? new ctors.MutationObserver(() => {
        observeAll();
        onChange();
      })
    : null;
  mutation?.observe(el, { childList: true });
  return () => {
    resize?.disconnect();
    mutation?.disconnect();
  };
}

export function useOverflowEdges<T extends HTMLElement>(): {
  ref: RefObject<T | null>;
  edges: OverflowEdges;
  sync: () => void;
} {
  const ref = useRef<T | null>(null);
  const [edges, setEdges] = useState<OverflowEdges>({ left: false, right: false });

  const sync = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const next = overflowEdges(el);
    setEdges((prev) => (prev.left === next.left && prev.right === next.right ? prev : next));
  }, []);

  useEffect(() => {
    const el = ref.current;
    sync();
    if (!el) return;
    el.addEventListener("scroll", sync, { passive: true });
    window.addEventListener("resize", sync);
    // Chips mount after data (live counts), so widths change after paint.
    const unwatch = watchStripContent(el, sync);
    return () => {
      el.removeEventListener("scroll", sync);
      window.removeEventListener("resize", sync);
      unwatch();
    };
  }, [sync]);

  return { ref, edges, sync };
}

export function OverflowCue({
  side,
  from = "from-white dark:from-neutral-950",
  testId,
}: {
  side: "left" | "right";
  /** Gradient start colour: the surface the strip sits on. */
  from?: string;
  testId?: string;
}) {
  const Icon = side === "right" ? ChevronRight : ChevronLeft;
  return (
    <div
      aria-hidden
      data-testid={testId}
      className={`pointer-events-none absolute inset-y-0 ${
        side === "right" ? "right-0 justify-end bg-gradient-to-l" : "left-0 justify-start bg-gradient-to-r"
      } flex w-10 items-center ${from} to-transparent`}
    >
      <Icon className="h-4 w-4 text-rally-muted" strokeWidth={2.5} />
    </div>
  );
}
