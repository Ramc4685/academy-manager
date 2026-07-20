# DS5 — Desktop Chromium Playwright project
Status: TODO
Size: S · Depends on: none (independent of DS1-4; can land any time) · Tracker: ../TRACKER.md

## Problem
CI Playwright runs only mobile viewports, so the admin `lg:` sidebar branch (the primary admin navigation on real screens) is never exercised end-to-end.

## Current behavior (verified 2026-07-20)
- `frontend/playwright.config.ts:47-56` defines exactly two projects: `chromium-mobile` (Pixel 7) and `webkit-mobile` (iPhone 14).
- `app/(admin)/layout.tsx:151-168` renders the desktop sidebar only at `lg:` (`hidden lg:flex ... lg:w-60`); below `lg` a mobile drawer is used instead. Nav links carry `data-testid="admin-nav-<slug>"` (layout.tsx:226) — same testids in both sidebar and drawer, but the drawer requires an open interaction first while the sidebar links are always visible.
- GAPS.md #8 confirms: "Only mobile viewports are configured; the desktop admin surface is untested at its real size."

## Proposed change
1. Add a third project to `playwright.config.ts`:
```ts
{
  name: "chromium-desktop",
  use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
  testMatch: /admin-(shell|students|registrations)\.spec\.ts/,
},
```
2. Scope it to 2-3 admin specs (real files in `frontend/e2e/specs/`): **`admin-shell.spec.ts`** (nav/layout — the spec that most benefits), **`admin-students.spec.ts`**, **`admin-registrations.spec.ts`**. Keep the desktop project narrow via `testMatch` so CI time grows minutes, not double.
3. Handle the sidebar/drawer navigation difference in specs: any spec that opens the mobile drawer (hamburger tap) before clicking `admin-nav-*` must branch. Preferred pattern — a shared helper in `frontend/e2e/` (e.g. `helpers/nav.ts`):
```ts
export async function gotoAdminNav(page: Page, slug: string) {
  const link = page.getByTestId(`admin-nav-${slug}`);
  if (!(await link.isVisible())) {
    await page.getByRole("button", { name: /menu|navigation/i }).click(); // drawer trigger — confirm exact accessible name in layout.tsx
  }
  await link.click();
}
```
   Visibility-based branching (not viewport sniffing) keeps the helper correct for both projects. Audit the three chosen specs for direct drawer interactions and route them through the helper.
4. Keep `NEXT_PUBLIC_E2E_AUTH_BYPASS=1` semantics unchanged — real-auth CI is MT3's scope, not this plan's.

## Implementation steps
1. Add project + testMatch to `playwright.config.ts`.
2. Add `gotoAdminNav` helper; refactor nav interactions in the three specs to use it.
3. Run locally: `pnpm exec playwright test --project=chromium-desktop`, then the full suite to confirm mobile projects unaffected.
4. Watch for desktop-only assertion drift (elements visible at 1280px that mobile specs assert hidden, sticky sidebar affecting scroll-into-view) — fix assertions to be project-agnostic.

## Files to change
- `frontend/playwright.config.ts`
- `frontend/e2e/helpers/nav.ts` (new — or nearest existing helpers module)
- `frontend/e2e/specs/admin-shell.spec.ts`
- `frontend/e2e/specs/admin-students.spec.ts`
- `frontend/e2e/specs/admin-registrations.spec.ts`

## Verification
- `pnpm typecheck` · `pnpm lint` · `pnpm e2e` (all three projects green, including `failOnFlakyTests` — config line 18 makes any timing race a hard fail, so run desktop 3× locally before merging).
- Visual check: Playwright HTML report screenshots confirm the sidebar (not drawer) renders in desktop runs.

## Risks / rollback
- Risk: CI wall-time increase — bounded by testMatch to 3 specs; workers=1 in CI (config:19) means additive minutes.
- Risk: `admin-students` had a prior webkit flake history (config comment :16-17) — desktop chromium is a different engine, but watch first CI runs.
- Rollback: delete the project block + helper usage; zero product code touched.

## PR checklist
- [ ] Release note: "CI now exercises the desktop admin layout (chromium-desktop Playwright project)."
- [ ] Update `docs/audit/TRACKER.md` DS5 row
- [ ] Flip this plan's Status → DONE (PR #NNN, date)
