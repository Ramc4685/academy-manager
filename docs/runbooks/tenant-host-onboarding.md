# Tenant host onboarding

Bringing a new academy live on its own host (`<slug>.courtmastr.com`, or a
custom domain) means registering that host in several allowlists. Two of them
live in Google consoles that expose no write API for what we need, so they are
forgotten silently: `blno-badminton.courtmastr.com` was missed in all of them
on 2026-09-01, and the failures surfaced one at a time as a parent walked
further into the funnel. While fixing that we found the flagship host
`academy.courtmastr.com` had been missing from the OAuth client for months with
nobody reporting the broken Google sign-in.

**Run the preflight before announcing a host, and again after any console
edit.** It is read-only — it never writes to Mongo and never mutates console
config.

```bash
source backend/.venv/bin/activate
python -m backend.scripts.tenant_host_preflight --host blno-badminton.courtmastr.com
# machine-readable, for CI or an onboarding checklist:
python -m backend.scripts.tenant_host_preflight --host blno-badminton.courtmastr.com --json
```

Configuration comes from the environment (`MONGO_URL`, `MONGO_DB_NAME`,
`V2_FIREBASE_PROJECT_ID` / `FIREBASE_PROJECT_ID`, `PLATFORM_BASE_DOMAIN`,
`FRONTEND_URL`) and can be overridden per flag; `--help` lists them.
`MONGO_URL` and `FRONTEND_URL` are required — the origin allowlist is built from
the deployment frontend URL, so the script exits `2` with a message rather than
reporting Gate 3 as a false `FAIL` when either is unset.

The script exits `0` only when the two gates it can conclusively verify (Gate 0
and Gate 3) pass. Gates 1 and 2 are console settings: Gate 1 can never be read
back, and Gate 2 degrades to `MANUAL` whenever the Identity Toolkit call is not
available (no credentials, missing IAM permission, API disabled). A `MANUAL`
gate is not a pass — confirm it by hand using the steps below.

> Keep the step text in this runbook identical to the strings the script prints
> (`google_oauth_steps`, `firebase_domain_steps`, `tenant_origins_steps` in
> `backend/scripts/tenant_host_preflight.py`). A unit test asserts this file
> still documents every gate heading.

---

## Gate 0 - Host resolves to the tenant

**Symptom when missing:** every request on the host 400s at tenant resolution —
the academy simply is not reachable there.

Checked automatically. `TenantResolver` accepts a host either as
`<slug>.<PLATFORM_BASE_DOMAIN>` (matching the academy's `slug`) or as a domain
registered in `academy_domains` / on the academy row.

If it fails: add the host to `academy_domains` with the academy's `academy_id`
and `status: "verified"`, or fix the academy `slug`.

## Gate 1 - Google OAuth client origins and redirect URI

**Symptom when missing:** "Continue with Google" dies with
`Error 400: redirect_uri_mismatch` before the consent screen.

Production runs `NEXT_PUBLIC_FIREBASE_AUTH_PROXY=1`, so `resolveAuthDomain`
(`frontend/lib/auth/auth-domain.ts`) uses the page's own host as `authDomain`
and the Google redirect target becomes `https://<tenant-host>/__/auth/handler`.
That is what turns "register one host, ever" into "register one host per
academy, forever".

Always `MANUAL` — Google exposes no API (not `gcloud`, not Terraform, not the
Admin SDK) for classic OAuth 2.0 web clients.

1. Open Google Cloud Console > APIs & Services > Credentials > the web OAuth
   2.0 client used by Firebase Auth
   (https://console.cloud.google.com/apis/credentials).
2. Add to Authorized JavaScript origins: `https://<host>`
3. Add to Authorized redirect URIs: `https://<host>/__/auth/handler`
4. Save, then wait a few minutes for Google to propagate the change.

Confirm by signing in with Google on the new host in a private window.

## Gate 2 - Firebase Auth authorized domains

**Symptom when missing:** sign-in clears the Google consent screen, then fails
at Firebase.

Checked automatically when a Firebase project id and usable Application Default
Credentials are present: the script GETs
`identitytoolkit.googleapis.com/admin/v2/projects/<project>/config` (with the
`x-goog-user-project` header — without it the API answers with a misleading
`SERVICE_DISABLED` 403) and looks for the host in `authorizedDomains`. Any
failure is reported as `MANUAL`, never as a pass or a fail.

1. Open Firebase Console > Authentication > Settings > Authorized domains.
2. Add domain: `<host>`
3. Verify with: `python -m backend.scripts.tenant_host_preflight --host <host>`

## Gate 3 - Tenant redirect/CORS origins include the host

**Symptom when missing:** the parent browses, registers, reaches "Review & pay",
and checkout fails with `redirect url origin not allowed`.

Checked automatically, and structural since PR #628: `TenantOriginsResolver`
rebuilds the allowlist from the academy's stored `slug` plus its
`academy_domains` rows with `status == "verified"` — no `CORS_ORIGINS` secret
edit is required for a normally onboarded host.

If it fails:

1. Add `<host>` to the `academy_domains` collection with
   `academy_id: "<academy_id>"` and `status: "verified"` (tenant creation writes
   the primary domain there; a custom domain must be added after ownership is
   verified).
2. Unverified domains are deliberately excluded from the redirect allowlist —
   do not relax that to make this gate pass.

---

## Onboarding checklist

- [ ] Academy created with its `slug`; primary domain written to
      `academy_domains` with `status: "verified"`.
- [ ] Gate 1 done in Google Cloud Console (origins + `/__/auth/handler`).
- [ ] Gate 2 done in Firebase Console (authorized domains).
- [ ] `tenant_host_preflight --host <host>` exits 0 with no `FAIL` line.
- [ ] Google sign-in completed end to end on the host in a private window.
- [ ] A test checkout reaches Stripe from the host.

Do not mark the academy live until every box is ticked. Existing hosts are
worth re-running periodically: the OAuth client list has drifted before without
anyone noticing.
