# fix-uic4-payouts-tabs-a11y

PR: #349

## What changed
Follow-up hardening for the UIC4 Payouts tablist that shipped in
[#346](https://github.com/Ramc4685/academy-manager/pull/346). Three fixes
to `app/(admin)/admin/payouts/page.tsx`, all behavior-preserving for the
payroll table itself:

- **URL is now the single source of truth for the active tab.** The tab was
  held in `useState` seeded from `?tab=`, so `router.replace()` and the
  local state could drift — a browser back/forward navigation changed the
  URL without changing the rendered tab. The `useState` is gone; `tab` is
  derived from `searchParams` on every render, and `selectTab` only calls
  `router.replace()`.
- **`Suspense` boundary added.** `useSearchParams()` in a client component
  opts the route into client-side rendering during static generation; the
  page body moved into a `PayoutsContent` child wrapped in `Suspense` with
  a lightweight fallback, which is the pattern Next requires to keep
  `/admin/payouts` statically generable.
- **Tablist keyboard semantics completed.** Tabs now carry
  `id`/`aria-controls` wired to a real `role="tabpanel"` wrapper with
  `aria-labelledby`, roving `tabIndex` (`0` for the selected tab, `-1` for
  the rest), and Arrow Left/Right handling that moves focus and selection
  with wraparound. Previously the tabs had `role="tab"`/`aria-selected` but
  no associated panel and no arrow-key support, so the WAI-ARIA tabs
  pattern was only half-implemented.

The payroll table, bulk generate/recompute/export mutations, query keys,
and every `data-testid` are byte-identical — the only change to that block
is indentation from the new tabpanel wrapper.

## Deploy notes
none — frontend-only. No API, schema, dependency, or env-var changes.

## Risk / rollback
Low. Deriving `tab` from the URL rather than state is strictly more correct
(it fixes back/forward drift); the worst case is an extra render on tab
switch, which `router.replace()` already caused. The `Suspense` fallback is
only visible during the client-render window that `useSearchParams()`
already forced. Keyboard changes are additive — mouse/touch selection and
the existing `admin-payouts` / `admin-coach-payslip` testids are unchanged,
so `admin-shell.spec.ts`'s coach-payslip redirect coverage still applies.
Rollback = revert this PR; #346's Payslips tab stays in place.

## Note on scope
This PR's branch predates #346's squash-merge, so it originally re-carried
all of #346's changes plus a `postcss` exact-pin. `origin/main` has been
merged in and the dependency changes dropped: main already forces
`postcss@<8.5.18: '>=8.5.18'` tree-wide and resolves to 8.5.23, so pinning
the direct dependency to exactly `8.5.18` would have downgraded postcss and
left two copies in the lockfile. What remains here is only the incremental
a11y/routing delta over merged #346.
