## README.md

<<<<<<< HEAD
- [contract] README.md:74 and README.md:161 say "Next.js 15"; `frontend/package.json:37` pins `next` 16.4.1 (React 19.3.0 at line 38 matches).
- [stale-not-built] README.md:162 lists `edge/` ("Retired Cloudflare Worker router kept for historical reference"); no `edge/` directory exists in the tree (the Worker is `frontend/wrangler.jsonc`, name `academy-next`).
- [undocumented] README.md:86-97 deployment pipeline omits the `Migrate Production` job (`.github/workflows/production.yml:783`, builds the image and dry-runs pending migrations between approval and backend deploy) and the `Sentry Release` job (`production.yml:1049`).
- [wording] README.md:90-91 "Validate — backend compile/tests, v2 DDD boundary checks, and Next.js typecheck/lint/build/E2E" understates the gate: `production.yml` also runs ruff/mypy, a real-Mongo contract job, dependency vulnerability scans, an OpenAPI drift check, a Worker runtime smoke, a real-auth E2E, script shellcheck and a final `CI Gate` (lines 168-733).
- [undocumented] README.md has no mention of Dependabot, the other workflows (`release-notes.yml`, `nightly-e2e.yml`, `restore-drill.yml`, `index-drift-audit.yml`, `mobile-build-check.yml`) or the `mobile/` directory (Capacitor apps), though README.md:156-165 claims to list the repo layout. `docs/ci-cd.md` is the closest doc. The current branch's Dependabot/Actions changes (`.github/dependabot.yml`, `.github/workflows/*`) therefore contradict nothing in the README.
- [undocumented] README.md:158-165 layout omits `mobile/`, `tests/`, `firebase-emulator/` and `memory/` at the repo root.
=======
- [undocumented] README.md:89-102 (Deployment pipeline) lists seven steps, but `.github/workflows/production.yml` also runs a `sentry-release` job (`production.yml:~1050-1117`, `release: courtmastr-frontend@${{ github.sha }}`) between smoke and the release record. The README does not mention it.
- [wording] README.md:92-93 says Validate covers "backend compile/tests, v2 DDD boundary checks, and Next.js typecheck/lint/build/E2E". The workflow also runs real-Mongo contract tests (`production.yml:167`), ruff/mypy lint (`production.yml:229`), dependency vulnerability scans, an OpenAPI drift check (`production.yml:312`), a Worker runtime smoke (`production.yml:352`), a real-auth E2E job and scripts/hook validation. The summary is incomplete, not wrong.
>>>>>>> origin/main
