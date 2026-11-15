## README.md

- [stale-not-built] README.md:162 lists `edge/` ("Retired Cloudflare Worker router kept for historical reference"), but no `edge/` directory exists at the repo root.
- [contract] README.md:74 and README.md:161 say Next.js 15, but `frontend/package.json:37` pins `next` 16.4.1 (React 19 at line 38 matches).
- [undocumented] README.md:158-165 (Layout) omits `mobile/` (Capacitor apps, CI in `.github/workflows/mobile-build-check.yml`), `memory/`, `tests/`, `firebase-emulator/`, and root docs `PROJECT.md`, `GAPS.md`, `SECURITY.md`.
- [wording] README.md:88 calls `production.yml` "the single GitHub Actions control plane", but `.github/workflows/` also holds `nightly-e2e.yml`, `release-notes.yml`, `restore-drill.yml`, `index-drift-audit.yml` and `mobile-build-check.yml`.
- [wording] README.md:80 says the scheduler timezone is "Set on backend"; it is set only as `SCHEDULER_TZ` in `backend/fly.toml:16` (a Fly env var, not application code).
