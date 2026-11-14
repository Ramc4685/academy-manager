## README.md

- [stale-not-built] README.md:162 lists `edge/` ("Retired Cloudflare Worker router kept for historical reference"), but no `edge/` directory exists at the repo root.
- [contract] README.md:74 and README.md:161 say Next.js 15, but `frontend/package.json:37` pins `next` 16.4.1 (React 19.3.0 at line 38 matches "React 19").
- [undocumented] README.md:158-165 (Layout) omits the `mobile/` directory (Capacitor apps), `memory/`, `tests/`, `firebase-emulator/` and the root docs `PROJECT.md`, `GAPS.md` and `SECURITY.md`. `mobile/` has a CI workflow, `.github/workflows/mobile-build-check.yml`.
- [wording] README.md:88 calls `production.yml` "the single GitHub Actions control plane", but `.github/workflows/` also holds `nightly-e2e.yml`, `release-notes.yml`, `restore-drill.yml`, `index-drift-audit.yml` and `mobile-build-check.yml`.
- [wording] README.md:80 says the scheduler timezone is "Set on backend". It is set only as `SCHEDULER_TZ` in `backend/fly.toml:16`. Much domain code instead uses explicit UTC or per-academy handling, for example `backend/v2/contexts/billing/application/use_cases/quote_enrollment.py:196`.
- [wording] README.md:116-118 says production email requires `APP_ENV=production`, a verified sender and an enable flag. `backend/v2/shared/config/settings.py:270` maps `APP_ENV` to `V2_ENV` only when `V2_ENV` is unset. I did not verify the full gate in `backend/v2/composition/email_adapters.py`.
