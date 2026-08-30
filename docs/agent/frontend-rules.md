# Frontend Rules

Use this file for the Next.js frontend, routing, UI, PWA, auth screens, admin/coach/parent pages, and browser verification.

---

## Commands

```bash
cd frontend
pnpm install
pnpm dev
pnpm typecheck
pnpm build
pnpm generate:api
```

---

## Frontend Rules

- Use Next.js App Router.
- Keep persona route groups separate: `(coach)`, `(parent)`, `(admin)`.
- Coach mobile pages must stay lightweight and touch-friendly.
- Use typed API clients from `lib/api/`.
- Use PWA/offline utilities from `lib/pwa/` and query persistence only where planned.
- Do not import admin-heavy libraries into coach routes.

---

## UI Rules

- Business truth belongs to backend, not frontend calculations.
- Frontend can format, filter, and present already-authorized data.
- Keep loading, empty, error, and retry states for user-facing async flows.
- Preserve accessibility basics: labels, focus states, keyboard paths, and semantic controls.
- Verify mobile behavior for coach and parent workflows.

---

## Firebase Frontend Rules

- Use Firebase Web SDK config from environment variables.
- Do not hard-code `REACT_APP_FIREBASE_API_KEY`.
- Authorized domains must match deployment hosts.
- Keep password reset, email verification, and invite acceptance consistent with backend Firebase rules.

---

## PWA and Offline Rules

- PWA/offline work belongs to v2 unless the task explicitly targets legacy.
- Offline reads and offline writes are different features.
- Do not queue offline writes unless the active ticket explicitly asks for it.
- Coach offline attendance writes are deferred until their planned wave.

---

## Frontend Verification

For UI changes:

1. Start the relevant dev server.
2. Open the affected route.
3. Verify the golden path.
4. Verify loading/error/empty states when touched.
5. Check mobile size for coach/parent flows.
6. Capture a screenshot when useful.

Useful URLs:

```txt
Legacy API health: http://127.0.0.1:8001/api/health
Frontend: http://localhost:<port> — per-worktree, printed by scripts/local_test_stack.sh status
  (derived from the repo root into 3001-3999; override with FRONTEND_PORT/PLAYWRIGHT_PORT)
```
