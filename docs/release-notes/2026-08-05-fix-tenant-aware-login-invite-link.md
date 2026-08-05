# fix-tenant-aware-login-invite-link

PR: #PENDING

## What changed
Parent login invites now land on the parent's **own academy portal**, on an
in-app branded page, instead of the project-wide Firebase page.

Before this, `generate_password_reset_link(email)` was called with no
`ActionCodeSettings`, so Firebase fell back to the project's default
`authDomain` and every academy's parents received the same link shape:

```
https://academy-courtmastr.firebaseapp.com/__/auth/action?mode=resetPassword&oobCode=…
```

Three problems, all fixed here:

1. **Unbranded.** There was no in-app handler — the only auth route was
   `/auth/magic` — so the app depended entirely on Firebase's hosted page.
2. **No tenant awareness.** No continue URL was passed at all.
3. **Wrong tenant on return.** Production `FRONTEND_URL` is
   `https://academy.courtmastr.com`, but this academy is served at
   `blno-academy.courtmastr.com`, so a parent was never returned to their own
   portal.

New pieces:

- **`backend/v2/shared/tenancy/firebase_action_link.py`** —
  `tenant_auth_action_link` re-hosts the Firebase link on the academy's own
  origin at `/auth/action`, preserving every query parameter (`mode`,
  `oobCode`, `apiKey`, `lang`, `continueUrl`) verbatim. The Firebase Console's
  action-URL setting is one project-wide value and can never point at a
  per-academy subdomain, so this server-side rewrite is the only way to get
  per-tenant landing.
- **`FirebaseAdminAdapter.generate_password_reset_link`** gains a keyword-only
  `portal_url`. When present it passes
  `ActionCodeSettings(url=<portal>/login, handle_code_in_app=False)` and applies
  the rewrite. Omitted, behaviour is exactly what it was before.
- **`SendLoginInvite`** gains an `AcademyPortalUrlLookup` port; composition
  implements it with `academy_frontend_url(settings.frontend_url, slug)` — the
  same slug rewrite invoice and digest emails already use, per ADR-0007. No
  hardcoded single `FRONTEND_URL`.
- **Frontend route `/auth/action`** — verifies the `oobCode`, takes a new
  password, calls `confirmPasswordReset`, then redirects to the validated
  `continueUrl`. Distinct states for expired / already-used / non-password
  links, each with a route back to sign-in.
- **`frontend/lib/auth/continue-url.ts`** — `safeContinuePath` open-redirect
  guard.

## Security
- **`emailVerified` is preserved.** `confirmPasswordReset` hits the same
  Identity Toolkit `accounts:resetPassword` endpoint as Firebase's hosted page,
  which marks the email verified as a side effect of proving mailbox
  possession. This is load-bearing: `_require_verified_password_provider_email`
  in `load_auth_claims.py` rejects password sign-in without it, and it has
  regressed before. Verified end to end against the Firebase Auth emulator — an
  account created with `email_verified=False`, the invite generated through the
  real adapter, the `oobCode` redeemed, and the resulting ID token carrying
  `sign_in_provider=password` **and** `email_verified=true`.
- **Open-redirect-safe.** `continueUrl` arrives as a query parameter, so it is
  never trusted as-is. Only a same-origin target is honoured; another academy's
  host, a foreign origin, a protocol-relative `//host`, a `javascript:` URL, or
  a scheme downgrade all collapse to `/login`.
- **Enumeration protection unchanged.** The up-front `get_user_by_email`
  existence check (added because enumeration protection makes
  `accounts:sendOobCode` return 200 with no `oobLink` instead of raising
  `EmailNotFoundError`) is untouched and still runs first.
- The rewrite does not weaken the `oobCode`: it is still single-use and
  short-lived, and is redeemed against Identity Toolkit, not against the page
  hosting it.

## Deploy notes
**Add each academy's portal domain to Firebase Authorized Domains** (Firebase
Console → Authentication → Settings → Authorized domains) — e.g.
`blno-academy.courtmastr.com`. `ActionCodeSettings` requires the continue URL's
domain to be authorized.

This is **not** a hard blocker. If Firebase rejects the continue URL
(`UNAUTHORIZED_DOMAIN` / `INVALID_CONTINUE_URI` / `INVALID_DYNAMIC_LINK_DOMAIN` /
`MISSING_CONTINUE_URI`), the adapter logs a warning and retries without
`ActionCodeSettings`, so the invite still sends. Only the post-reset redirect is
lost; the branded in-app landing still works, because the rewrite needs no
authorized domain. Watch for the log line
`Firebase rejected continue URL for portal …` after deploy — it names any
academy whose domain still needs adding.

No migration. No new environment variables. Takes effect on the next invite
sent. The Firebase Console action-URL setting is deliberately **not** changed,
so email-verification links from the register flow keep using the hosted page
and are unaffected.

## Risk / rollback
Low blast radius, and the new behaviour is opt-in per call site: `portal_url`
is keyword-only and defaults to `None`, so any caller that does not pass it
gets exactly the previous link. Only `SendLoginInvite` passes it today. An
academy with no resolvable slug also degrades to the old link rather than
failing.

The `/auth/action` page is additive — no existing route, auth path, or Firebase
Console setting changes. `/auth/magic` is untouched.

The one behaviour that must not regress is `emailVerified=true`; it is covered
by the emulator verification above and documented in the adapter docstring and
in `confirmPasswordResetValue`.

To roll back, revert this PR: invites return to the generic
`<project>.firebaseapp.com` link (today's production behaviour), and the unused
`/auth/action` page becomes dead code. No data migration. Authorized-domain
entries added during deploy are harmless if left in place.

## Verification
- `backend/v2/tests` — 2685 passed.
- `lint-imports` — 6 contracts kept, 0 broken.
- `ruff check v2` and `ruff format --check v2` — clean (886 files).
- `pnpm typecheck` and `pnpm lint` — clean (5 warnings, all pre-existing).
- `pnpm vitest run lib/ components/ app/` — 41 passed.
- Firebase Auth emulator: `email_verified` False → True through the rewritten
  link; ID token `sign_in_provider=password` with `email_verified=true`.
- Route-inventory audit gates updated in this commit: manifest entry for
  `/auth/action`, plus the route counts in
  `test_inventory_acceptance_coverage.py` and
  `test_inventory_control_evidence.py` (79 → 80).
