# PWA Safe-Area Header Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every persona shell header tappable in the installed iOS app by padding it below the status bar, and keep the view/academy switcher menus on screen on phones.

**Architecture:** The app already opts into drawing under the status bar (`black-translucent` + `viewport-fit=cover`), so the fix is purely CSS: add `env(safe-area-inset-top)` to the top padding of the five sticky shell headers, the admin mobile drawer, and `env(safe-area-inset-bottom)` to the toast stack. Menu clamping is a tiny pure decision function plus a layout-effect hook shared by the two switchers.

**Tech Stack:** Next.js 15 app router, React 19, Tailwind 4 (arbitrary values only), Vitest (node environment, no DOM library).

## Global Constraints

- Work in the worktree `.worktrees/pwa-safe-area` on branch `fix/pwa-safe-area-header`. Never edit the main checkout.
- Frontend commands run from `frontend/` inside that worktree; if `node_modules` is missing run `pnpm install --frozen-lockfile` first (a symlink to the main checkout's `node_modules` does not work).
- Use Tailwind arbitrary values exactly as written in the spec: `pt-[calc(0.75rem+env(safe-area-inset-top,0px))]`, `pt-[env(safe-area-inset-top,0px)]`, `bottom-[max(1rem,env(safe-area-inset-bottom,0px))]`.
- Do not add dependencies.
- Release note file `docs/release-notes/2026-09-03-fix-pwa-safe-area-header.md` with the three exact sections `## What changed`, `## Deploy notes`, `## Risk / rollback` and the real PR number.
- Git hooks block `--amend`, `rebase`, and `--no-verify`; make new commits instead.

---

### Task 1: Safe-area padding on shell headers, drawer, and toast

**Files:**
- Create: `frontend/app/shell-safe-area.test.ts`
- Modify: `frontend/app/(admin)/layout.tsx` (RallyTopbar header ~line 371, MobileDrawer aside ~line 320)
- Modify: `frontend/app/(coach)/layout.tsx` (header ~line 60)
- Modify: `frontend/app/(parent)/layout.tsx` (header ~line 62)
- Modify: `frontend/app/(student)/layout.tsx` (header ~line 44)
- Modify: `frontend/app/(platform)/layout.tsx` (header ~line 55)
- Modify: `frontend/components/ds/toast.tsx` (container ~line 92)

**Interfaces:**
- Consumes: nothing.
- Produces: no code interface; a string-level regression test that later tasks must keep green.

- [ ] **Step 1: Write the failing guard test**

`frontend/app/shell-safe-area.test.ts`:

```ts
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * The installed PWA draws under the iOS status bar
 * (apple-mobile-web-app-status-bar-style=black-translucent + viewport-fit=cover).
 * Every sticky shell header must therefore pad by env(safe-area-inset-top),
 * or its buttons land in the status-bar zone where iOS swallows taps.
 * The layouts need auth to render, so this guards the source text instead.
 */
const HEADER_SAFE_TOP = "pt-[calc(0.75rem+env(safe-area-inset-top,0px))]";
const BARE_SAFE_TOP = "pt-[env(safe-area-inset-top,0px)]";
const TOAST_SAFE_BOTTOM = "bottom-[max(1rem,env(safe-area-inset-bottom,0px))]";

const APP = path.resolve(__dirname);

function source(rel: string): string {
  return readFileSync(path.join(APP, rel), "utf8");
}

describe("persona shell headers pad for the iOS status bar", () => {
  it.each(["(admin)", "(coach)", "(parent)", "(student)", "(platform)"])(
    "%s layout header carries the safe-area top padding",
    (group) => {
      const src = source(`${group}/layout.tsx`);
      expect(src).toContain(HEADER_SAFE_TOP);
      // The inset must be added to the existing padding, not replace it.
      expect(src).not.toMatch(/<header[^>]*className="[^"]*\bpy-3\b/);
    },
  );

  it("admin mobile drawer pads its top edge", () => {
    expect(source("(admin)/layout.tsx")).toContain(BARE_SAFE_TOP);
  });

  it("toast stack clears the home indicator", () => {
    expect(source("../components/ds/toast.tsx")).toContain(TOAST_SAFE_BOTTOM);
    expect(source("../components/ds/toast.tsx")).not.toContain(" bottom-4 ");
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && pnpm vitest run app/shell-safe-area.test.ts`
Expected: 7 failures (5 headers, drawer, toast), each with "expected ... to contain".

- [ ] **Step 3: Pad the admin topbar and drawer**

In `frontend/app/(admin)/layout.tsx`, the `RallyTopbar` header:

```tsx
    <header
      className="sticky top-0 z-30 border-b bg-white/95 backdrop-blur px-4 pb-3 pt-[calc(0.75rem+env(safe-area-inset-top,0px))] md:px-6"
      style={{ borderColor: "var(--rally-line)" }}
    >
```

The `MobileDrawer` aside:

```tsx
      <aside
        className="relative z-50 flex flex-col w-64 h-full shadow-xl overflow-y-auto pt-[env(safe-area-inset-top,0px)]"
        style={{ background: "var(--rally-night)", color: "var(--rally-bright)" }}
        aria-label="Admin navigation"
        data-testid="admin-mobile-drawer"
      >
```

- [ ] **Step 4: Pad the coach, parent, student, and platform headers**

Each of these four files has a header whose className starts `sticky top-0 z-10 flex items-center justify-between px-4 py-3`. Replace `py-3` in that className with `pb-3 pt-[calc(0.75rem+env(safe-area-inset-top,0px))]`, leaving everything else untouched. For example, `frontend/app/(coach)/layout.tsx`:

```tsx
      <header
        className="sticky top-0 z-10 flex items-center justify-between px-4 pb-3 pt-[calc(0.75rem+env(safe-area-inset-top,0px))]"
        style={{ background: "#0a0f1c", borderBottom: "1px solid #1e293b" }}
      >
```

Apply the same replacement to `(parent)`, `(student)`, and `(platform)` layouts (their `style` props differ; do not change them).

- [ ] **Step 5: Pad the toast stack**

In `frontend/components/ds/toast.tsx`:

```tsx
      <div className="pointer-events-none fixed inset-x-0 bottom-[max(1rem,env(safe-area-inset-bottom,0px))] z-[60] flex flex-col items-center gap-2 px-4 sm:inset-x-auto sm:right-4 sm:items-end">
```

- [ ] **Step 6: Run the guard test and the static checks**

Run: `cd frontend && pnpm vitest run app/shell-safe-area.test.ts && pnpm lint && pnpm typecheck`
Expected: 7 passed; lint and typecheck clean.

- [ ] **Step 7: Commit**

```bash
git add frontend/app/shell-safe-area.test.ts "frontend/app/(admin)/layout.tsx" "frontend/app/(coach)/layout.tsx" "frontend/app/(parent)/layout.tsx" "frontend/app/(student)/layout.tsx" "frontend/app/(platform)/layout.tsx" frontend/components/ds/toast.tsx
git commit -m "fix(pwa): pad shell headers, drawer and toasts for iOS safe areas

In the installed app the page draws under the status bar, so every sticky
header sat in the zone where iOS blurs content and swallows taps. Add
env(safe-area-inset-top) to the five persona headers and the admin drawer,
and env(safe-area-inset-bottom) to the toast stack.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Keep switcher menus on screen

**Files:**
- Create: `frontend/components/persona/menu-anchor.ts`
- Create: `frontend/components/persona/menu-anchor.test.ts`
- Create: `frontend/components/persona/use-clamp-menu.ts`
- Modify: `frontend/components/persona/persona-switcher.tsx` (~lines 39-41 and 86-91)
- Modify: `frontend/components/admin/tenant-switcher.tsx` (~lines 106 and 120-125)

**Interfaces:**
- Produces: `shouldAnchorLeft(rect: { left: number }, margin?: number): boolean` and `useClampMenuToViewport(menuRef: RefObject<HTMLElement | null>, open: boolean): void`.

- [ ] **Step 1: Write the failing pure-function test**

`frontend/components/persona/menu-anchor.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { shouldAnchorLeft } from "./menu-anchor";

describe("shouldAnchorLeft", () => {
  it("flips a menu whose left edge is off screen", () => {
    expect(shouldAnchorLeft({ left: -120 })).toBe(true);
  });

  it("flips a menu whose left edge is inside the margin", () => {
    expect(shouldAnchorLeft({ left: 4 })).toBe(true);
  });

  it("leaves a menu that is fully on screen alone", () => {
    expect(shouldAnchorLeft({ left: 40 })).toBe(false);
  });

  it("honours a custom margin", () => {
    expect(shouldAnchorLeft({ left: 12 }, 16)).toBe(true);
    expect(shouldAnchorLeft({ left: 12 }, 8)).toBe(false);
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && pnpm vitest run components/persona/menu-anchor.test.ts`
Expected: FAIL, "Failed to resolve import ./menu-anchor".

- [ ] **Step 3: Implement the decision function and the hook**

`frontend/components/persona/menu-anchor.ts`:

```ts
/**
 * Dropdown menus in the shell headers are anchored `right-0` to their
 * trigger. On phones the trigger can sit near the left edge, so a menu wider
 * than the space to its left renders off screen. Returns true when the menu
 * should be re-anchored to the trigger's left edge instead.
 */
export function shouldAnchorLeft(rect: { left: number }, margin = 8): boolean {
  return rect.left < margin;
}
```

`frontend/components/persona/use-clamp-menu.ts`:

```ts
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
```

- [ ] **Step 4: Run the pure-function test**

Run: `cd frontend && pnpm vitest run components/persona/menu-anchor.test.ts`
Expected: 4 passed.

- [ ] **Step 5: Wire the hook into the persona switcher**

In `frontend/components/persona/persona-switcher.tsx`, add the import after the `getCurrentUser` import:

```ts
import { useClampMenuToViewport } from "./use-clamp-menu";
```

After `const containerRef = useRef<HTMLDivElement | null>(null);` add:

```ts
  const menuRef = useRef<HTMLUListElement | null>(null);
  useClampMenuToViewport(menuRef, open);
```

Add `ref={menuRef}` to the menu `<ul>`:

```tsx
        <ul
          ref={menuRef}
          role="listbox"
          aria-label="Available views"
          data-testid="persona-switcher-menu"
          className="absolute right-0 mt-1 w-44 rounded-md border border-rally-line bg-white shadow-lg z-40 py-1"
        >
```

Note: `useClampMenuToViewport` is called before the early `return null` for single-role users, so hook order is stable.

- [ ] **Step 6: Wire the hook into the tenant switcher**

In `frontend/components/admin/tenant-switcher.tsx`, add the import:

```ts
import { useClampMenuToViewport } from "@/components/persona/use-clamp-menu";
```

Next to the existing `containerRef` declaration (before any early returns in the component) add:

```ts
  const menuRef = useRef<HTMLUListElement | null>(null);
  useClampMenuToViewport(menuRef, open);
```

and add `ref={menuRef}` to the menu `<ul data-testid="tenant-switcher-menu">`. If `useRef` is not already imported from `react` in this file, add it to the existing react import. Check that the component has no early `return` between the top of the function body and the point where the hook is called; if it does, move the hook call above that return.

- [ ] **Step 7: Run unit tests and static checks**

Run: `cd frontend && pnpm test:unit && pnpm lint && pnpm typecheck`
Expected: all vitest files pass (including Task 1's guard); lint and typecheck clean.

- [ ] **Step 8: Run the shell e2e specs that exercise the switchers**

Run: `cd frontend && pnpm exec playwright test e2e/specs/admin-shell.spec.ts --project=chromium-desktop`
(If the project name differs, list them with `pnpm exec playwright test --list | head` and pick the chromium desktop one.) Expected: pass. These specs open the persona and tenant switchers on desktop, where the clamp is a no-op.

- [ ] **Step 9: Commit**

```bash
git add frontend/components/persona/menu-anchor.ts frontend/components/persona/menu-anchor.test.ts frontend/components/persona/use-clamp-menu.ts frontend/components/persona/persona-switcher.tsx frontend/components/admin/tenant-switcher.tsx
git commit -m "fix(shell): keep view and academy switcher menus on screen on phones

Both menus are right-anchored to a trigger that sits near the left edge on
narrow screens, so they opened off the left of the viewport. Measure once
on open and flip to left-anchored when needed.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Device verification, release note, and PR

**Files:**
- Create: `docs/release-notes/2026-09-03-fix-pwa-safe-area-header.md`

- [ ] **Step 1: Verify on the iOS simulator as an installed app**

1. Start the frontend dev server from the worktree (`cd frontend && pnpm dev`), note the port.
2. Boot an iPhone simulator, open Safari at `http://localhost:<port>/admin`, sign in with the local dev admin.
3. Share → Add to Home Screen → Add. Launch the home-screen icon.
4. Screenshot: the header content must sit fully below the clock and the Dynamic Island, with the header colour extending up behind them.
5. Tap "Admin view" → the menu must open fully on screen and "Coach view" must be tappable and navigate.
6. Navigate to `/coach/today`: the dark header must also clear the status bar; the calendar, messages, view switcher, and logout buttons must respond to taps.

If the simulator cannot be driven in this session, state that plainly in the PR body and ask the user to confirm on device before merge. Do not claim device verification that did not happen.

- [ ] **Step 2: Push and open the PR**

```bash
git push -u origin fix/pwa-safe-area-header
gh pr create --base main --title "fix(pwa): shell headers tappable under the iOS status bar; switcher menus stay on screen" --body-file /dev/stdin <<'BODY'
## Summary
- The installed app draws under the iOS status bar (`black-translucent` + `viewport-fit=cover`) but no header padded for it, so every persona shell header sat in the zone where iOS blurs content and swallows taps. Admins could not open "Admin view" to switch to the coach view; coaches could not reach the header buttons.
- Add `env(safe-area-inset-top)` to the five shell headers and the admin drawer, `env(safe-area-inset-bottom)` to the toast stack.
- The view and academy switcher menus are right-anchored and opened off the left edge on phones; they now flip to left-anchored when needed.

## Test plan
- [ ] `pnpm test:unit` (new guard test + menu-anchor test)
- [ ] `pnpm lint && pnpm typecheck`
- [ ] admin-shell e2e on chromium desktop
- [ ] iOS simulator, installed to home screen: header below status bar, view switcher opens on screen (see screenshots)

Design: docs/superpowers/specs/2026-09-03-pwa-safe-area-header-design.md

🤖 Generated with [Claude Code](https://claude.com/claude-code)
BODY
```

- [ ] **Step 3: Write the release note with the real PR number**

`docs/release-notes/2026-09-03-fix-pwa-safe-area-header.md` (replace `<number>` with the number `gh pr create` printed):

```markdown
# fix-pwa-safe-area-header

PR: #<number>

## What changed
On phones with the app installed to the home screen, every persona header
(admin, coach, parent, student, platform) rendered under the iOS status bar,
so the view switcher, academy switcher, logout, calendar and messages buttons
were blurred and could not be tapped. Headers, the admin drawer, and toasts
now pad for the device safe areas. The view and academy switcher menus also
stay on screen instead of opening off the left edge.

## Deploy notes
None. Pure frontend CSS/layout; no migration, no env vars. Installed users
pick it up on the next service-worker refresh.

## Risk / rollback
Low. Desktop browsers resolve the safe-area insets to 0, so nothing changes
there. Revert the PR to restore the previous headers.
```

- [ ] **Step 4: Commit the release note and push**

```bash
git add docs/release-notes/2026-09-03-fix-pwa-safe-area-header.md
git commit -m "docs: release note for PWA safe-area header fix

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

- [ ] **Step 5: Watch CI**

Wait for "CI Gate" and "Release Notes Gate" to pass on the PR. If the redirect e2e specs time out, rerun failed jobs once before treating it as a regression.
