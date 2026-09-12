# Auth and Connect hardening

PR: #0

## What changed

- Fixes #538 — `email_verified` was only enforced when `firebase.sign_in_provider == "password"`, so a token from any other provider carrying `email_verified=false` (or omitting it entirely) resolved straight to whichever account owns that email address — an account-takeover surface the moment a non-password provider is enabled. `load_auth_claims.py` and `register_public_parent.py` previously duplicated this check; both now call one shared policy, `backend/v2/contexts/identity/application/token_claims.py::require_verified_email`, which requires a verified claim from every provider and treats a missing claim as unverified. Magic-link custom tokens (server-minted, provisioned with `email_verified=false` by design) stay exempt so that flow keeps working.
- Fixes #547 — Stripe Connect's OAuth `state` HMAC secret no longer falls back to the webhook secret and then to an empty string. The Connect callback route is unauthenticated, so the HMAC over `state` is the only thing binding a returning Stripe account to an academy; an empty key let anyone forge a valid `state` for any `academy_id` and bind their own Stripe account to a victim academy. `backend/v2/composition/admin.py` now leaves both Connect use cases unwired when no dedicated state secret is configured, and the routes already degrade to their existing not-configured path.

## Deploy notes

- No migrations. No new environment variables are required, but production must have its own dedicated Stripe Connect OAuth state secret configured (distinct from the webhook secret) for Connect onboarding to work post-deploy — if it was previously relying on the webhook-secret fallback, onboarding will report "not configured" until a real state secret is set.
- Frontend untouched; backend-only deploy.

## Risk / rollback

- Both changes are fail-closed hardening with no behavior change for already-correct configurations (password-provider sign-in with a real verified claim; a properly configured Connect state secret). The only observable change for misconfigured environments is that previously-permissive paths now reject or degrade to "not configured" instead of silently succeeding.
- Rollback: revert this PR. No data migration is needed either direction.
