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

## Deploy notes
None. Dependency bump only — no backend change, no migration, no new env vars.

## Risk / rollback
`pnpm exec tsc --noEmit`, `pnpm lint`, `pnpm test:unit` (286 tests) and
`pnpm test:node` (134 tests) all pass clean on the merged branch. The two held-back
packages (`@fullcalendar/react`, `typescript`/`eslint`) will come back in a future
Dependabot run once `@fullcalendar/daygrid` ships a stable v7 and once
`typescript-eslint` / `eslint-plugin-react` publish releases compatible with
`typescript@7` / `eslint@10`. Rollback is reverting the PR; nothing here is
runtime-visible so a revert is low-risk.
