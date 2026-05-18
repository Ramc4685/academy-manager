# Frontend Consolidation

CourtMastr now has one production frontend deployable: `frontend-next/`.

## Target

- `frontend-next/` is the active v2 app for admin, coach, parent, login, and public parent registration.
- `frontend/` is deprecated CRA source retained only for reference until a deletion PR.
- New UI work, BFF integration, PWA/offline behavior, and Firebase Auth changes belong in `frontend-next/`.

## Cutover Sequence

1. Deploy only `frontend-next/` from GitHub Actions.
2. Route `academy.courtmastr.com/*` directly to the `academy-next` Cloudflare Worker with a Worker Route, not a Cloudflare Custom Domain record.
3. Verify admin, coach, parent, login, and public registration against production BFFs.
4. Delete or archive `frontend/` once no operator needs it for code reference.

## Rules

- Do not add new product pages to `frontend/`.
- Do not duplicate a workflow across both apps.
- Do not route production browser traffic through the retired `academy-edge-router`.
- If a legacy page still has required behavior, port it into `frontend-next/` using v2 BFF endpoints before cutover.
- The backend source of truth remains Firebase Auth for authentication and MongoDB for authorization.
