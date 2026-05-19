# Frontend Consolidation

CourtMastr now has one production frontend deployable: `frontend/`.

## Target

- `frontend/` is the active Next.js app for admin, coach, parent, login, and public parent registration.
- New UI work, BFF integration, PWA/offline behavior, and Firebase Auth changes belong in `frontend/`.

## Cutover Sequence

1. Deploy only `frontend/` from GitHub Actions.
2. Route `academy.courtmastr.com/*` directly to the `academy-next` Cloudflare Worker with a Worker Route, not a Cloudflare Custom Domain record.
3. Verify admin, coach, parent, login, and public registration against production BFFs.
4. Keep old CRA source out of the deploy path. Recover it from git history only if needed for reference.

## Rules

- Do not reintroduce a second frontend app.
- Do not leave the old `courtmastr-academy` Cloudflare Pages project bound to `academy.courtmastr.com`; it wins over the Worker route and serves the deprecated CRA bundle.
- Do not route production browser traffic through the retired `academy-edge-router`.
- If a legacy page still has required behavior, port it into `frontend/` using v2 BFF endpoints before cutover.
- The backend source of truth remains Firebase Auth for authentication and MongoDB for authorization.
