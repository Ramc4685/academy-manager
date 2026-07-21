# DS3 — Add missing DS primitives (FormField, Skeleton, EmptyState, Modal, Toast)
Status: IN PROGRESS — code complete on `fix/DS3-primitives`; typecheck + lint green; `pnpm e2e` pending (dev-env disk-full). Flip to DONE (PR #NNN, date) once e2e passes and the PR merges.
Size: M · Depends on: DS2 · Tracker: ../TRACKER.md

Third step of DS1→DS4. Requires DS2 merged (primitives must be built on token classes, not hex). DS4 (parent-surface migration) consumes every primitive added here and must not start first.

## Problem
`components/ds/` has Button/Chip/Card/Lane but none of the primitives every page re-invents:
- No form field wrapper — labels/errors wired ad hoc, `aria-describedby` mostly absent.
- No Skeleton — loading states are bespoke per page.
- No EmptyState — empty lists render ad-hoc paragraphs.
- No Modal — zero focus traps repo-wide; dialogs are hand-rolled `role="dialog" aria-modal="true"` divs with no Escape handling, no focus management, no focus-return.
- No Toast — **no mutation-feedback system exists**; success/error is an inline `<p role="alert">` per page.

## Current behavior (verified 2026-07-20)
- `app/(parent)/parent/children/page.tsx:343-349` — inline cancel-enrollment "dialog": a `role="dialog" aria-modal="true"` div rendered in-flow (not even overlaid), raw hex border `#fecaca`, no focus trap/Escape.
- `app/(admin)/admin/requests/page.tsx:640-657` — `DialogShell`: fixed overlay with backdrop-click close, `role="dialog" aria-modal="true"`, but no focus trap, no Escape key, no focus-return; used by `DenyDialog` below it.
- Success feedback pattern: `<p role="status">`/`<p role="alert">` inline (e.g. children/page.tsx:352).
- The audit's monolith split map notes `RallyDialog`/`DialogActions`/`Field`/`Th`/`TableSkeleton` are duplicated across the three admin monolith pages — the Modal/FormField/Skeleton here are the canonical homes those extractions (MT5) will target.

## Proposed change
Add five primitives to `frontend/components/ds/`, each token-based (per DS2) and theme-aware.

### FormField (`components/ds/form-field.tsx`)
```ts
interface FormFieldProps {
  label: ReactNode;
  htmlFor: string;            // id of the wrapped control
  error?: string | null;      // rendered with role="alert", wired via aria-describedby
  hint?: ReactNode;           // also joined into aria-describedby
  required?: boolean;
  children: ReactNode;        // the input/select/textarea; cloned or documented to receive aria-describedby + aria-invalid
}
```
Renders `<label htmlFor>`, hint (`id={htmlFor}-hint`), error (`id={htmlFor}-error`, `role="alert"`). Export a helper `fieldDescribedBy(htmlFor, {hint, error})` so controls can wire `aria-describedby`/`aria-invalid` without cloneElement magic.

### Skeleton (`components/ds/skeleton.tsx`)
```ts
interface SkeletonProps { variant?: "line" | "block" | "circle"; width?: string | number; height?: string | number; lines?: number; className?: string }
```
Uses the existing `shimmer` keyframes already defined in `globals.css:74-77`. Also export `TableSkeleton({ rows, cols })` (canonicalizing the duplicated admin helper).

### EmptyState (`components/ds/empty-state.tsx`)
```ts
interface EmptyStateProps { icon?: ReactNode; title: string; description?: ReactNode; action?: ReactNode /* usually a <Button> */; compact?: boolean }
```

### Modal (`components/ds/modal.tsx`)
```ts
interface ModalProps {
  open: boolean;
  onClose: () => void;        // Escape + backdrop click + close button all route here
  title: ReactNode;           // rendered as heading, referenced by aria-labelledby
  children: ReactNode;
  footer?: ReactNode;         // action row
  size?: "sm" | "md" | "lg";
  initialFocusRef?: RefObject<HTMLElement>;
  dismissable?: boolean;      // default true; false disables backdrop/Escape (destructive confirms in-flight)
}
```
Requirements: `role="dialog" aria-modal="true" aria-labelledby`; focus trap (Tab/Shift-Tab cycle within); Escape closes; focus-return to the invoking element on close; body scroll lock; rendered in a portal. No new dependency needed — a ~40-line trap is fine, or `focus-trap-react` if preferred (decide in PR).

### Toast (`components/ds/toast.tsx`)
```ts
type ToastKind = "success" | "error" | "info";
interface ToastOptions { kind?: ToastKind; title: string; description?: string; durationMs?: number /* default 5000; error kind defaults to sticky */ }
// Provider mounted once per persona layout:
function ToastProvider({ children }: { children: ReactNode }): JSX.Element;
// Hook:
function useToast(): { toast: (opts: ToastOptions) => void; dismiss: (id: string) => void };
```
Region: single `aria-live="polite"` (errors `role="alert"`) container, bottom-center on mobile / bottom-right on desktop, capped stack of 3. Note: this *adds* a feedback channel; existing inline `<p role="alert">` error banners stay valid for form-level errors — Toast is for async mutation outcomes.

## First-adopter migrations (prove the API, no big-bang sweep)
- **Modal**: `admin/requests/page.tsx` `DialogShell`/`DenyDialog` (:640+) and the parent cancel-enrollment dialog (`parent/children/page.tsx:343`) — the two ad-hoc dialogs the audit cites.
- **FormField**: one form on `admin/requests` deny-reason input + one parent form (children add-child).
- **Skeleton/EmptyState**: `parent/waivers` (smallest parent page) loading + empty list.
- **Toast**: mount ToastProvider in `(parent)` layout only; convert cancel-enrollment success message (children/page.tsx:352) to a toast. Admin/coach layouts adopt in later PRs.

## Files to change
- New: `frontend/components/ds/form-field.tsx`, `skeleton.tsx`, `empty-state.tsx`, `modal.tsx`, `toast.tsx` (+ optional `index.ts` barrel)
- First adopters: `frontend/app/(admin)/admin/requests/page.tsx`, `frontend/app/(parent)/parent/children/page.tsx`, `frontend/app/(parent)/parent/waivers/page.tsx`, `frontend/app/(parent)/layout.tsx`

## Verification
- `pnpm typecheck` · `pnpm lint` · `pnpm e2e` (parent-self-service.spec.ts covers the children cancel flow; admin specs cover requests).
- Manual a11y check on Modal: Tab cycles inside, Escape closes, focus returns to trigger, VoiceOver announces title.
- Visual check: dialogs look unchanged apart from consistent chrome; toast appears on cancel success.

## Risks / rollback
- Risk: focus-trap edge cases (portals + Next.js app router). Mitigate with an e2e assertion (keyboard Escape closes deny dialog) added to admin-registrations or requests coverage.
- Risk: converting success text to Toast changes what e2e asserts — update specs in the same PR.
- Rollback: primitives are additive; first-adopter commits are separable.

## PR checklist
- [ ] Release note: "New accessible DS primitives (FormField/Skeleton/EmptyState/Modal/Toast); requests + parent-children dialogs migrated."
- [ ] Update `docs/audit/TRACKER.md` DS3 row (and note MT5 dependency satisfied)
- [ ] Flip this plan's Status → DONE (PR #NNN, date)
