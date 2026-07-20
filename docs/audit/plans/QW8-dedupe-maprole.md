# QW8 — Dedupe mapRoleToStatus
Status: TODO
Size: XS · Depends on: none · Tracker: ../TRACKER.md

## Problem
The same role→chip-variant mapper is copy-pasted in two files, both with an `any` return type, defeating the typed `Chip` API.

## Current behavior (verified)
- `frontend/app/(admin)/admin/users/page.tsx:83-87` — `function mapRoleToStatus(role: string): any` (admin→"enrolled", coach→"autopayOn", else "manual"); consumed at line 120 as `<Chip variant={mapRoleToStatus(user.role)} ...>`.
- `frontend/components/admin/AdminUsersDirectory.tsx:259-263` — byte-identical copy.
- `frontend/components/ds/chip.tsx:54-60` — `Chip` accepts `variant?: ChipVariant` with a `CHIP_VARIANTS[variant] ?? paid` fallback, so `any` currently hides nothing at runtime but kills compile-time checking.

## Implementation steps
1. Create `frontend/lib/admin/role-chip.ts` (new; `frontend/lib/` is the established helper home):
   ```ts
   import type { ChipVariant } from "@/components/ds/chip";
   export function roleToChipVariant(role: string): ChipVariant {
     if (role === "admin") return "enrolled";
     if (role === "coach") return "autopayOn";
     return "manual";
   }
   ```
   If `ChipVariant` isn't exported from `chip.tsx`, export the type there first (type-only change).
2. Replace both local `mapRoleToStatus` definitions with an import of `roleToChipVariant`; delete the duplicates.
3. Note (don't fix here): UIC1 merges these two surfaces — this helper survives that merge either way.

## Verification
- `git grep -n "mapRoleToStatus" frontend` → zero hits.
- `pnpm typecheck` passes (and fails if you temporarily return `"bogus"` — proves the typing is live).
- `pnpm lint` passes; admin users page renders identical chips (e2e or manual smoke on /admin/users).

## Risks / rollback
- None — pure refactor, identical mapping. Rollback: revert commit.

## PR checklist
- [ ] Release note if backend/ or frontend/ changed (per AGENTS.md)
- [ ] TRACKER.md updated
- [ ] Plan Status flipped to DONE
