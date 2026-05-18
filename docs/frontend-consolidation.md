# Frontend Consolidation Plan

CourtMastr is converging on one production frontend: `frontend-next/`.

## Target

- `frontend-next/` is the active v2 app for admin, coach, parent, login, and public parent registration.
- `frontend/` is legacy fallback only until `academy.courtmastr.com` is cut over and the soak window clears.
- New UI work, BFF integration, PWA/offline behavior, and Firebase Auth changes belong in `frontend-next/`.

## Cutover Sequence

1. Keep `academy-next.courtmastr.com` serving `frontend-next/`.
2. Verify admin, coach, parent, login, and public registration against production BFFs.
3. Move `academy.courtmastr.com` to the v2 Next app.
4. Keep legacy reachable only through the documented fallback route during the quiet window.
5. Stop deploying `frontend/` after the quiet window.
6. Delete or archive `frontend/` once no production route depends on it.

## Rules

- Do not add new product pages to `frontend/`.
- Do not duplicate a workflow across both apps.
- If a legacy page still has required behavior, port it into `frontend-next/` using v2 BFF endpoints before cutover.
- The backend source of truth remains Firebase Auth for authentication and MongoDB for authorization.
