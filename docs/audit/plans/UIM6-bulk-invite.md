# UIM6 — Bulk user invite UI
Status: TODO
Size: S · Depends on: UIC1 (same surface — the users directory may have become the merged role-tab screen; build the modal against whichever page hosts the directory at merge time) · Tracker: ../TRACKER.md

## User value
Onboarding an academy means inviting dozens of parents one-by-one via the single-create form. The backend supports up to 100 invites per call (create + login-invite email each); a paste/CSV modal turns hours into minutes.

## Backend status (verified — routes, DTO fields)
`backend/v2/interfaces/admin/directory_routes.py:121` `POST /users/bulk-invite`, persona `admin`:
- Request `BulkInviteRequest {users: BulkInviteItem[] (1-100), reason: str = "bulk parent invite" (1-500)}`; `BulkInviteItem {email (1-254), display_name (1-120)}` (`admin/views.py:197-204`)
- Response `BulkInviteResponse {created: int, skipped: int, failed: int, results: BulkInviteResultItem[]}`; item `{email, status: "created"|"skipped"|"failed", user_id?, detail?}` (views.py:207-218)
- Semantics (route body :133-174): **parent role only** (hardcoded `role="parent"`); duplicate email ⇒ `skipped` ("email already exists"); other failure ⇒ `failed`; each created user gets a login-invite email best-effort (invite failure does NOT flip the item to failed). Partial success is normal — always 200.

## Frontend to build (pages/components/queries — concrete)
- Host: users directory page `frontend/app/(admin)/admin/users/page.tsx` (or the UIC1 merged directory) — "Bulk invite parents" button next to the existing single-create action.
- Modal (`frontend/components/admin/bulk-invite-dialog.tsx`):
  1. **Input step**: textarea accepting `email, display name` per line AND a CSV file picker (client-side parse, no upload endpoint); optional reason field (default preserved).
  2. **Preview step**: parsed table with client-side validation (email format, name 1-120, ≤100 rows — chunk or block above 100), dedupe within the batch.
  3. **Result step**: created/skipped/failed counts + per-row status table from `results`, with retry-failed-only convenience (re-submit failed subset).
- API fn `bulkInviteParents(body: BulkInviteRequest)` in `frontend/lib/api/admin.ts` via `apiFetch`.
- Mutation invalidates `queryKeys.admin.users()` (all-roles key `["admin","users","all"]` and `users("parent")` — invalidate the `["admin","users"]` prefix).

## Backend to build (if any — route, use case, tests, manifest registration)
None. No new frontend route (modal on existing page) → update the `/admin/users` entry in `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json` (add the modal to `controls.modals`, add workflow + acceptance + risk edge lines; keep `test_audit_inventory_manifest.py` count invariants).

## Implementation steps (phased if L; each phase one PR)
1. Single PR: API fn + dialog (3 steps) + button on the directory page + manifest entry update. Check TRACKER for UIC1 status first and target the merged screen if it landed.

## Files to change/create
- Create: `frontend/components/admin/bulk-invite-dialog.tsx`
- Modify: `frontend/app/(admin)/admin/users/page.tsx` (or UIC1's merged directory page), `frontend/lib/api/admin.ts`, `docs/qa/2026-06-28-production-scale-local-inventory-manifest.json`

## Verification
- `pnpm typecheck && pnpm lint`; manifest test green
- Manual: paste 3 rows (one duplicate email) → result shows 2 created / 1 skipped; list refreshes with new parents; >100 rows blocked client-side; malformed rows flagged before submit

## Risks / rollback
- Each invite sends a real email — make the confirm copy explicit ("sends login invites to N parents"); in staging use seeded/test addresses.
- Long batches run serially server-side; keep the submit button in a loading state (no timeout retry — duplicate submits would double-invite; rely on `skipped` idempotency for created users).
- Rollback: remove button + dialog; endpoint untouched.

## PR checklist (release note · TRACKER.md · plan Status → DONE)
- [ ] Release note
- [ ] Update TRACKER.md row UIM6
- [ ] Plan Status → DONE
