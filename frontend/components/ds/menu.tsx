"use client";

/**
 * Overflow-menu primitive: a trigger button plus an absolutely-positioned
 * `role="menu"` list. Hand-rolled — no dependency added — following the
 * `RallySessionPicker` pattern in `app/(admin)/admin/sessions/[id]/dialogs.tsx`,
 * which exists to dodge a macOS Chrome native-select rendering issue. The
 * `Frontend Static` gate already goes red repo-wide on re-issued GHSAs, so a
 * new dependency here is not worth the risk.
 *
 * Keyboard: Escape closes and restores focus to the trigger. ArrowDown/
 * ArrowUp/Home/End move a roving highlight. Enter/Space activates the
 * highlighted item. Outside click closes.
 */

import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";

export interface MenuItem {
  key: string;
  label: ReactNode;
  onSelect: () => void;
  disabled?: boolean;
  /** Rendered after the label, e.g. an OwnerOnlyHint for a disabled entry. */
  hint?: ReactNode;
  danger?: boolean;
}

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
  const [activeIndex, setActiveIndex] = useState<number>(-1);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const menuId = useId();

  const enabledIndexes = items
    .map((item, index) => (item.disabled ? -1 : index))
    .filter((index) => index !== -1);

  useEffect(() => {
    if (!open) return;
    const onDocMouseDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [open]);

  useEffect(() => {
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
      {open && (
        <div
          id={menuId}
          role="menu"
          aria-orientation="vertical"
          onKeyDown={onMenuKeyDown}
          className={`absolute z-20 mt-1 min-w-[180px] rounded-md border border-rally-line bg-white py-1 shadow-lg ${
            align === "end" ? "right-0" : "left-0"
          }`}
        >
          {items.map((item, index) => (
            <button
              key={item.key}
              ref={(el) => {
                itemRefs.current[index] = el;
              }}
              type="button"
              role="menuitem"
              tabIndex={index === activeIndex ? 0 : -1}
              disabled={item.disabled}
              onClick={() => {
                if (item.disabled) return;
                setOpen(false);
                triggerRef.current?.focus();
                item.onSelect();
              }}
              className={`flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm ${
                item.disabled
                  ? "cursor-not-allowed text-rally-muted opacity-60"
                  : item.danger
                    ? "text-status-red-800 hover:bg-status-red-50"
                    : "text-rally-ink hover:bg-rally-paper"
              }`}
            >
              <span>{item.label}</span>
              {item.hint}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
