## README.md

- [wording] README:74 says "Next.js 15 / React 19" for the web layer. `frontend/package.json:37` pins `next` 16.4.1 (AGENTS.md:94 also says Next.js 16, served via OpenNext).
- [wording] README:161 says "Next.js 15 app". Same drift as above (`frontend/package.json:37`).
- [stale-not-built] README:162 lists `edge/` ("Retired Cloudflare Worker router kept for historical reference"). No `edge/` directory exists at the repo root.
- [undocumented] README:158-165 Layout omits `mobile/` (Capacitor iOS/Android apps, `mobile/capacitor.config.ts`), `tests/`, `firebase-emulator/`, `memory/` and `.claude/` agent tooling.
- [undocumented] README:20-31 and README:57-66 do not mention the native mobile apps (Capacitor, native Google/Apple sign-in), although CI has `.github/workflows/mobile-build-check.yml`.
- [undocumented] README:86-97 pipeline omits a database migrations dry-run step (`migrate-production` job, `.github/workflows/production.yml:~800-919`) that gates `deploy-backend` (`production.yml:924`).
- [wording] README:88 calls `production.yml` the "single" control plane. Other workflows exist (`index-drift-audit.yml`, `nightly-e2e.yml`, `restore-drill.yml`, `release-notes.yml`, `mobile-build-check.yml`).
- [wording] README:80 "Scheduler timezone `America/Chicago` set on backend". It is set as `SCHEDULER_TZ` in `backend/fly.toml:16`, not a general backend timezone.

Rechecked after the `fix-issue-batch.js` security-lens change: it touches nothing README.md describes.
