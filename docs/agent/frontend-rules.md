# Frontend Rules

Use this file for CRA React, Next.js v2 frontend, routing, UI, PWA, auth screens, admin/coach/parent pages, and browser verification.

---

## Commands

Legacy CRA frontend:

```bash
cd frontend
yarn install
yarn start
yarn test --watchAll=false
yarn build
```

v2 Next frontend, when present:

```bash
cd frontend-next
pnpm install
pnpm dev
pnpm typecheck
pnpm build
pnpm generate:api
```

---

## Legacy Frontend Rules

- Legacy app entry point is `frontend/src/App.js`.
- Legacy API client is `frontend/src/lib/api.js`.
- Auth state lives in `frontend/src/contexts/AuthContext.jsx` and related auth libs.
- Pages are grouped by persona under `frontend/src/pages/admin`, `coach`, `parent`, `auth`, and `shared`.
- Keep existing UI patterns unless the task is specifically redesign work.
- Do not add new global state libraries without a clear need.
- Use existing Radix/shadcn-style components and `lucide-react` where appropriate.

---

## v2 Frontend Rules

When `frontend-next/` exists:

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
Legacy frontend: http://localhost:3000
Legacy API health: http://127.0.0.1:8001/api/health
v2 frontend, when present: http://localhost:3001
```
