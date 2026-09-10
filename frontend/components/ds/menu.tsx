"use client";

/**
 * Overflow-menu primitive: a trigger button plus a `role="menu"` list rendered
 * into `document.body` through a portal. Hand-rolled — no dependency added —
 * following the `RallySessionPicker` pattern in
 * `app/(admin)/admin/sessions/[id]/dialogs.tsx`, which exists to dodge a macOS
 * Chrome native-select rendering issue. The `Frontend Static` gate already goes
 * red repo-wide on re-issued GHSAs, so a new dependency here is not worth the
 * risk.
 *
 * The portal is load-bearing, not cosmetic (#713): the roster's action column
 * is `sticky right-0 z-10`, and a positioned element with a z-index starts its
 * own stacking context. An absolutely-positioned menu inside row N's cell can
 * therefore never paint above row N+1's cell, so every menu item except the
 * last one sat underneath the row below and clicks landed on that row's
 * controls. Portalled + `position: fixed`, the menu escapes the cell's stacking
 * context entirely.
 *
 * Keyboard: Escape closes and restores focus to the trigger. ArrowDown/
 * ArrowUp/Home/End move a roving highlight. Enter/Space activates the
 * highlighted item. Outside click closes.
 */

import Link from "next/link";
import { createPortal } from "react-dom";
import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type ReactNode,
} from "react";

type MenuItemHref = Parameters<typeof Link>[0]["href"];

export interface MenuItem {
  key: string;
  label: ReactNode;
  /** Omitted for navigation items, which carry `href` instead. */
  onSelect?: () => void;
  /** Renders the item as a link, so cmd/ctrl-click and open-in-new-tab work. */
  href?: MenuItemHref;
  disabled?: boolean;
  /** Rendered after the label, e.g. an OwnerOnlyHint for a disabled entry. */
  hint?: ReactNode;
  danger?: boolean;
}

const MENU_MIN_WIDTH = 180;
const VIEWPORT_MARGIN = 8;
const TRIGGER_GAP = 4;

export function OverflowMenu({
  trigger,
  items,
  align = "end",
  className = "",
}: {
  trigger: ReactNode;
  items: MenuItem[];
  align?: "start" | "end";
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);
  const [activeIndex, setActiveIndex] = useState<number>(-1);
  const rootRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const itemRefs = useRef<Array<HTMLElement | null>>([]);
  const menuId = useId();

  const enabledIndexes = items
    .map((item, index) => (item.disabled ? -1 : index))
    .filter((index) => index !== -1);

  useEffect(() => {
    setMounted(true);
  }, []);

  const updatePosition = useCallback(() => {
    const triggerEl = triggerRef.current;
    if (!triggerEl) return;
    const rect = triggerEl.getBoundingClientRect();
    const menuEl = menuRef.current;
    const width = menuEl?.offsetWidth || MENU_MIN_WIDTH;
    const height = menuEl?.offsetHeight ?? 0;

    let top = rect.bottom + TRIGGER_GAP;
    const overflowsBelow = top + height > window.innerHeight - VIEWPORT_MARGIN;
    const fitsAbove = rect.top - TRIGGER_GAP - height >= VIEWPORT_MARGIN;
    if (height > 0 && overflowsBelow && fitsAbove) {
      top = rect.top - TRIGGER_GAP - height;
    }

    const rawLeft = align === "end" ? rect.right - width : rect.left;
    const maxLeft = Math.max(VIEWPORT_MARGIN, window.innerWidth - width - VIEWPORT_MARGIN);
    const left = Math.min(Math.max(rawLeft, VIEWPORT_MARGIN), maxLeft);

    setPosition({ top, left });
  }, [align]);

  useLayoutEffect(() => {
    if (!open) {
      setPosition(null);
      return;
    }
    updatePosition();
  }, [open, updatePosition, items.length]);

  useEffect(() => {
    if (!open) return;
    const onReposition = () => updatePosition();
    // Capture phase so scrolls inside the roster's horizontal scroll container
    // (which never reach window in the bubble phase) move the menu too.
    window.addEventListener("scroll", onReposition, true);
    window.addEventListener("resize", onReposition);
    return () => {
      window.removeEventListener("scroll", onReposition, true);
      window.removeEventListener("resize", onReposition);
    };
  }, [open, updatePosition]);

  useEffect(() => {
    if (!open) return;
    const onDocMouseDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (rootRef.current?.contains(target)) return;
      // The menu is portalled, so it is NOT inside rootRef; without this check
      // a mousedown on a menu item would close the menu before its click fired.
      if (menuRef.current?.contains(target)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [open]);

  useLayoutEffect(() => {
    if (open && activeIndex >= 0) {
      itemRefs.current[activeIndex]?.focus();
    }
  }, [open, activeIndex]);

  const closeAndRestoreFocus = () => {
    setOpen(false);
    triggerRef.current?.focus();
  };

  const moveActive = (direction: 1 | -1) => {
    if (enabledIndexes.length === 0) return;
    const currentPos = enabledIndexes.indexOf(activeIndex);
    const nextPos =
      currentPos === -1
        ? direction === 1
          ? 0
          : enabledIndexes.length - 1
        : (currentPos + direction + enabledIndexes.length) % enabledIndexes.length;
    setActiveIndex(enabledIndexes[nextPos]);
  };

  const onTriggerKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      setOpen(true);
      setActiveIndex(enabledIndexes[0] ?? -1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
      setActiveIndex(enabledIndexes[enabledIndexes.length - 1] ?? -1);
    }
  };

  const onMenuKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    switch (event.key) {
      case "Escape":
        event.preventDefault();
        closeAndRestoreFocus();
        break;
      case "ArrowDown":
        event.preventDefault();
        moveActive(1);
        break;
      case "ArrowUp":
        event.preventDefault();
        moveActive(-1);
        break;
      case "Home":
        event.preventDefault();
        if (enabledIndexes.length > 0) setActiveIndex(enabledIndexes[0]);
        break;
      case "End":
        event.preventDefault();
        if (enabledIndexes.length > 0) setActiveIndex(enabledIndexes[enabledIndexes.length - 1]);
        break;
      case "Tab":
        setOpen(false);
        break;
      default:
        break;
    }
  };

  const itemClass = (item: MenuItem) =>
    `flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm ${
      item.disabled
        ? "cursor-not-allowed text-rally-muted opacity-60"
        : item.danger
          ? "text-status-red-800 hover:bg-status-red-50"
          : "text-rally-ink hover:bg-rally-paper"
    }`;

  const menuStyle: CSSProperties = {
    position: "fixed",
    top: position?.top ?? 0,
    left: position?.left ?? 0,
    // Opacity, not visibility: the menu is measured and placed in a layout
    // effect one frame after mount, and a `visibility: hidden` element cannot
    // take focus — keyboard opening would land nowhere.
    opacity: position ? 1 : 0,
  };

  const menu = (
    <div
      ref={menuRef}
      id={menuId}
      role="menu"
      aria-orientation="vertical"
      onKeyDown={onMenuKeyDown}
      style={menuStyle}
      className="z-50 min-w-[180px] rounded-md border border-rally-line bg-white py-1 shadow-lg"
    >
      {items.map((item, index) => {
        const setItemRef = (el: HTMLElement | null) => {
          itemRefs.current[index] = el;
        };
        const shared = {
          role: "menuitem" as const,
          tabIndex: index === activeIndex ? 0 : -1,
          className: itemClass(item),
        };
        const body = (
          <>
            <span>{item.label}</span>
            {item.hint}
          </>
        );
        if (item.href && !item.disabled) {
          return (
            <Link
              key={item.key}
              ref={setItemRef}
              href={item.href}
              {...shared}
              onClick={() => {
                setOpen(false);
                item.onSelect?.();
              }}
            >
              {body}
            </Link>
          );
        }
        return (
          <button
            key={item.key}
            ref={setItemRef}
            type="button"
            {...shared}
            disabled={item.disabled}
            onClick={() => {
              if (item.disabled) return;
              setOpen(false);
              triggerRef.current?.focus();
              item.onSelect?.();
            }}
          >
            {body}
          </button>
        );
      })}
    </div>
  );

  return (
    <div ref={rootRef} className={`relative inline-block ${className}`}>
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => {
          setOpen((wasOpen) => {
            const willOpen = !wasOpen;
            if (willOpen) setActiveIndex(-1);
            return willOpen;
          });
        }}
        onKeyDown={onTriggerKeyDown}
      >
        {trigger}
      </button>
      {open && mounted && createPortal(menu, document.body)}
    </div>
  );
}
