"use client";

import { useLayoutEffect, type RefObject } from "react";

import { shouldAnchorLeft } from "./menu-anchor";

/**
 * Once a right-anchored menu opens, measure it and flip it to left-anchored
 * if it would fall off the left edge of the viewport. The menu element is
 * conditionally rendered, so closing unmounts it and nothing needs resetting.
 */
export function useClampMenuToViewport(menuRef: RefObject<HTMLElement | null>, open: boolean): void {
  useLayoutEffect(() => {
    if (!open) return;
    const el = menuRef.current;
    if (!el) return;
    if (shouldAnchorLeft(el.getBoundingClientRect())) {
      el.style.left = "0";
      el.style.right = "auto";
    }
  }, [menuRef, open]);
}
