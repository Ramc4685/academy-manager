# UIM9 — Platform-fallback billing visibility
Status: TODO
Size: S · Depends on: none · Tracker: ../TRACKER.md

## User value
`allow_platform_charge_fallback` is the escape hatch that routes parent charges to the **platform** Stripe account when the academy's connected account isn't charge-ready — i.e. money parks in the platform account (GAPS.md #4). Today the flag is invisible: it can only be inspected/flipped via API or a Mongo write. A settings card makes the risk state visible to admins, makes every flip deliberate and reasoned, and is the mitigation surface for the money-parking gap.

## Backend status (verified)
- `GET /admin/billing/settings/platform-fallback` — `backend/v2/interfaces/admin/billing_routes.py:104`. Returns `{ allow_platform_charge_fallback: bool }`.
- `PUT /admin/billing/settings/platform-fallback` — `backend/v2/interfaces/admin/billing_routes.py:122`. Body `{ enabled: bool, reason?: string }`, same response shape. Both `require_persona("admin")`; 503 if use cases unwired.
- Semantics (`backend/v2/contexts/billing/application/use_cases/billing_settings_admin.py`):
  - `SetPlatformChargeFallback` is idempotent — setting the current value is a no-op and writes **no** audit entry.
  - Real flips append a `BillingAuditEntry` (`action="platform_fallback_toggled"`, actor, before/after, reason) **before** the settings write, so the flag never changes unaudited.
  - The flag is consumed by checkout paths (`parent_billing.py:625`, `enroll_child_in_session_type.py:150`): when the connected account isn't charge-ready they fall back to a PLATFORM charge instead of failing closed.
- Fallback-taken payment counter: **no existing endpoint exposes one.** Grep of `backend/v2/interfaces/` found no billing-health route surfacing fallback usage, and the charge paths do not stamp a fallback marker on the payment document — only the toggle itself is audited. See optional backend addition below.

## Frontend to build
A "Platform charge fallback" card in admin Settings (billing section):
- Current state badge — prominent warning styling when ON ("charges are routing to the platform account").
- Toggle action opening a confirm dialog that requires a `reason` (free text, sent in the PUT body). Reason should be strongly encouraged (require non-empty in the UI even though the API allows null).
- Copy explaining exactly what ON means (funds park in platform account; temporary escape hatch).
- Data layer: fetch/mutate via `apiFetch` (`frontend/lib/api/client.ts` conventions), TanStack Query v5 `useQuery` + `useMutation` with invalidation, query key in `frontend/lib/query/keys.ts` (e.g. `admin.platformFallback: () => ["admin", "billing", "platform-fallback"]`).

## Backend to build (if any)
Optional (recommended follow-up, not required for this plan): a visibility counter of payments actually taken via fallback.
- Cheapest honest version: stamp `charged_via_platform_fallback: true` on the payment/checkout record at the two fallback call sites (`parent_billing.py`, `enroll_child_in_session_type.py`), then expose a count on an existing admin billing summary endpoint. Follow DDD layering (use case change in `contexts/billing/application/use_cases`, Mongo in infrastructure) and register any new route in `backend/v2/tests/unit/test_audit_inventory_manifest.py`.
- If deferred, the card should at least link to the billing audit log filtered to `platform_fallback_toggled` so flips are reviewable.

## Implementation steps
1. API client: `getPlatformFallback()` / `setPlatformFallback({enabled, reason})` + types.
2. Query key + hooks (query + mutation with `invalidateQueries`).
3. Settings card with state badge, explanation copy, confirm-with-reason dialog, error banner (typed `ApiError` → `role="alert"`).
4. (Optional, separate PR) fallback-usage stamping + count as described above.

## Files to change/create
- `frontend/lib/api/v2/billingSettings.ts` (or nearest existing admin billing client module).
- `frontend/lib/query/keys.ts`.
- `frontend/app/(admin)/admin/settings/page.tsx` (or the settings section component UIC7 establishes) — add card.

## Verification
- Manual: GET renders current state; toggling ON→ON is a no-op (no audit entry — verify in Mongo/audit view); real flip persists, audit entry has actor + reason; page reload reflects new state.
- 404 for non-admin personas (wrong-persona convention) — existing backend behavior, spot-check.
- Frontend type-check/lint; add an e2e happy path if the settings page already has one.

## Risks / rollback
- The PUT changes real charge routing — the confirm dialog copy must be unambiguous. UI is read/write of an existing audited endpoint; rollback = revert PR (flag state itself is data, unaffected).
- Optional counter touches charge paths; keep it in its own PR so this card can ship risk-free.

## PR checklist
- [ ] Release note line
- [ ] TRACKER.md row updated (Status, PR/Issue)
- [ ] This plan's Status → DONE (PR #NNN, date)
