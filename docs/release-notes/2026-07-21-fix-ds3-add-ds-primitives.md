# fix-ds3-add-ds-primitives

PR: TBD

## What changed
New accessible design-system primitives in `frontend/components/ds/`, each
token-based (per DS2) and theme-aware:

- **FormField** — `<label>` + hint + error (`role="alert"`) with a
  `fieldDescribedBy()` helper for wiring `aria-describedby`/`aria-invalid`.
- **Skeleton** / **TableSkeleton** — loading placeholders on the existing
  `shimmer` keyframes; `TableSkeleton` canonicalizes the per-page admin helper.
- **EmptyState** — icon/title/description/action, `compact` variant.
- **Modal** — first focus trap in the app: `role="dialog" aria-modal`
  `aria-labelledby`, Tab/Shift-Tab cycle, Escape to close, focus-return to the
  trigger, body scroll lock, portal-rendered. `dismissable={false}` disables
  backdrop/Escape for in-flight destructive confirms.
- **Toast** — the app's first mutation-feedback system: `ToastProvider` +
  `useToast()`, capped stack of 3, success/info `role="status"` and error
  `role="alert"` (errors sticky by default), bottom-center on mobile /
  bottom-right on desktop.

First-adopter migrations (API-proving only, not a full sweep — that is DS4):
- `admin/requests/page.tsx` — `DialogShell` now wraps `Modal` (all three
  request dialogs gain the focus trap); local `Skeleton`/`EmptyState` helpers
  replaced by DS `TableSkeleton`/`EmptyState`; deny-reason textarea wrapped in
  `FormField`.
- `parent/children/page.tsx` — `CancelEnrollmentDialog` migrated to
  `Modal` + `FormField` + `Skeleton`; cancel-success message converted to a
  toast (dialog closes on success).
- `parent/waivers/page.tsx` — loading + "no waiver required" states migrated
  to `Skeleton`/`EmptyState`.
- `(parent)/layout.tsx` — mounts `ToastProvider` (parent surface only).
- `e2e/specs/parent-self-service.spec.ts` — cancel-success assertion updated
  to target the toast and assert the dialog closes.

Audit item DS3; unblocks DS4 (parent-surface migration) and MT5 (monolith
page split can extract into these canonical homes).

## Deploy notes
none — frontend-only, additive components, no migrations, no env vars.

## Risk / rollback
Primitives are additive; first-adopter commits are separable. Main behavioral
change is cancel-enrollment success moving from an inline in-dialog message to
a toast (spec updated in the same change). Focus-trap edge cases (portals +
app router) are the primary risk area; revert the PR if a dialog misbehaves —
no data or API surface touched.

## Verification
`pnpm typecheck` and `pnpm lint` pass. `pnpm e2e` was not run in this session
due to a full-disk condition in the dev environment; must be run green before
merge (parent-self-service.spec covers the migrated cancel flow).
