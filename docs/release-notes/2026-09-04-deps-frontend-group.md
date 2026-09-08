# deps-frontend-group

PR: #649

## What changed
Dependabot's grouped frontend dependency bump (21 updates across
`frontend/package.json` and `frontend/pnpm-lock.yaml`). Most updates are routine
patch/minor bumps. Two packages in the group were held back from what Dependabot
proposed because nothing in the toolchain supports them yet:

- `@fullcalendar/react` stays pinned at `6.1.21` (Dependabot proposed `7.0.2`).
  `@fullcalendar/daygrid` has no stable v7 release (only `7.0.0-rc.0` and betas), and
  mixing `@fullcalendar/react@7` (built on the new `@fullcalendar/core@7` /
  `@full-ui/headless-calendar` plugin architecture) with `@fullcalendar/daygrid@6`
  fails to typecheck (`Type 'PluginDef' is not assignable to type 'PluginInput'`) in
  `components/admin/AdminCalendarView.tsx` and `components/calendar/PersonaCalendarView.tsx`.
- `typescript` stays pinned at `5.9.3` (Dependabot proposed `7.0.2`) and `eslint` stays
  pinned at `9.13.0` (Dependabot proposed `10.9.1`). `typescript-eslint` (pulled in via
  `eslint-config-next`) only supports `typescript >=4.8.4 <6.1.0` as of its latest
  release (`8.70.0`), and `eslint-plugin-react`'s latest release (`7.37.5`) only
  supports `eslint` up to `^9.7`. Taking either bump breaks `pnpm lint` outright.

Every other package in the group (Radix UI, Sentry, Serwist, TanStack Query, Firebase,
Next.js/`eslint-config-next` to `16.3.4`, lucide-react, wrangler, Vitest, Playwright,
etc.) moved to the version Dependabot proposed. `pnpm-lock.yaml` was regenerated with
`pnpm install` after aligning `package.json`, and the branch was merged forward onto
current `main` (27 commits, including #662/#664/#665/#661/#666/#667/#683 and the
role-model and lifecycle-followup work).

### Also: unblocks the repo-wide `Frontend Static` audit failure

`pnpm audit --audit-level=high` was failing on **`main` and therefore on every open PR**,
so nothing could merge. Three separate causes, all fixed here:

- **2 critical, `next` (GHSA-p293-qw3h-jr36, GHSA-2xp9-vwfh-vxw4, `<15.5.24`).** `main`
  pinned `next@15.5.21`. This PR's bump to `16.3.4` clears both, and takes the
  `sharp <0.35.4` high (GHSA-rgj7-g3m4-5g8c) with it, since that reached us through
  `next`'s bundled `sharp`.
- **2 high, `js-yaml` (GHSA-2883-xcg3-v3hh).** A re-issued advisory that moves the fixed
  versions one patch past the pins already in `frontend/pnpm-workspace.yaml`, so
  `js-yaml@3: ^3.15.1 -> ^3.15.2` and `js-yaml@4: ^4.3.1 -> ^4.3.2`. Both are published;
  dev-only, transitive via `eslint` and `@lhci/cli`.
- **1 high, `extract-zip` (GHSA-7pqw-9j4j-h8q3).** The same unvalidated-symlink issue the
  workspace already documents and ignores as `GHSA-jmr9-qjv8-65gv`, re-issued under a new
  id, so the ignore stopped matching. The original justification is unchanged and still
  verified: `2.0.1` is **still** the latest version on the registry (the advisory names
  `>=2.0.2` as patched, but no such release exists), and it is dev-only via
  `@lhci/cli -> lighthouse -> puppeteer-core -> @puppeteer/browsers`, never reaching the
  deployed bundle. The new id is added alongside the old one, with the same note.

After this, `scripts/ci/dependency_audit.sh pnpm audit --audit-level=high` exits 0.

## Deploy notes
None. Dependency bump only — no backend change, no migration, no new env vars.

## Risk / rollback
`pnpm exec tsc --noEmit`, `pnpm lint`, `pnpm test:unit` (286 tests) and
`pnpm test:node` (134 tests) all pass clean on the merged branch. The two held-back
packages (`@fullcalendar/react`, `typescript`/`eslint`) will come back in a future
Dependabot run once `@fullcalendar/daygrid` ships a stable v7 and once
`typescript-eslint` / `eslint-plugin-react` publish releases compatible with
`typescript@7` / `eslint@10`. Rollback is reverting the PR — but note that reverting also
restores the two critical `next` advisories and re-breaks the `Frontend Static` audit gate
on every open PR, so a revert should be paired with a direct `next >= 15.5.24` bump.

The two `extract-zip` highs remain reported-but-ignored; that is the pre-existing,
documented exception (no patched release exists upstream), not a regression introduced
here. Remove both ids once the puppeteer chain drops `extract-zip` or `2.0.2` ships.
